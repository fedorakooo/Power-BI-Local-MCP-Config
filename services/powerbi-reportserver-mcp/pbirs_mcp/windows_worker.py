"""Standalone, report-scoped interactive Windows MCP worker.

Uses standard Win32/UI automation; does not depend on Codex's Computer Use host.
Each action consumes a fresh screenshot token. The agent interprets screenshots
and orchestrates the workflow; this is not an unattended Windows service.
"""
from __future__ import annotations
import argparse
import base64
import io
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

SHORTCUTS = {'tab': '{TAB}', 'shift_tab': '+{TAB}', 'enter': '{ENTER}', 'escape': '{ESC}',
             'up': '{UP}', 'down': '{DOWN}', 'left': '{LEFT}', 'right': '{RIGHT}',
             'space': '{SPACE}', 'select_all': '^a', 'save': '^s', 'save_as': '{F12}',
             'open': '^o', 'backspace': '{BACKSPACE}'}


def safe_file_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,100}\.pbix', value, re.I):
        raise ValueError('Use a simple PBIX release filename')
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *['COM'+str(i) for i in range(1,10)], *['LPT'+str(i) for i in range(1,10)]}:
        raise ValueError('Reserved Windows filename')
    return value


class Win32Backend:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('The Desktop worker requires interactive Windows')
        import ctypes
        from ctypes import wintypes
        # Explicit signatures prevent truncating 64-bit process/desktop handles.
        ctypes.windll.user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        ctypes.windll.user32.OpenInputDesktop.restype = wintypes.HANDLE
        ctypes.windll.user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        ctypes.windll.user32.CloseDesktop.restype = wintypes.BOOL
        ctypes.windll.user32.GetLastActivePopup.argtypes = [wintypes.HWND]
        ctypes.windll.user32.GetLastActivePopup.restype = wintypes.HWND
        ctypes.windll.kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        ctypes.windll.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        ctypes.windll.user32.SetProcessDPIAware()
        import win32gui, win32process, win32api, win32con, win32ts
        from pywinauto import Application, keyboard, mouse
        self.gui, self.process, self.api, self.con, self.ts = win32gui, win32process, win32api, win32con, win32ts
        self.Application, self.keyboard, self.mouse = Application, keyboard, mouse

    def ensure_unlocked(self):
        import ctypes
        desktop = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
        if not desktop:
            raise RuntimeError('Windows is locked or the interactive desktop is unavailable')
        ctypes.windll.user32.CloseDesktop(desktop)

    def windows(self):
        self.ensure_unlocked()
        result = []
        def visit(hwnd, _):
            if not self.gui.IsWindowVisible(hwnd) or self.gui.GetWindow(hwnd, self.con.GW_OWNER):
                return
            _, pid = self.process.GetWindowThreadProcessId(hwnd)
            try:
                process = self.api.OpenProcess(0x1000, False, pid)
                import ctypes
                buffer = ctypes.create_unicode_buffer(32768)
                length = ctypes.c_ulong(len(buffer))
                okay = ctypes.windll.kernel32.QueryFullProcessImageNameW(int(process), 0, buffer, ctypes.byref(length))
                process.Close()
                if okay and Path(buffer.value).name.lower() == 'pbidesktop.exe':
                    result.append({'hwnd': hwnd, 'pid': pid, 'title': self.gui.GetWindowText(hwnd), 'executable': buffer.value})
            except Exception:
                return
        self.gui.EnumWindows(visit, None)
        return result

    def capture(self, main):
        self.ensure_unlocked()
        wrapper = self.Application(backend='win32').connect(handle=main['hwnd']).window(handle=main['hwnd']).wrapper_object()
        foreground = self.gui.GetForegroundWindow()
        if self.gui.GetAncestor(foreground, 3) != main['hwnd']:
            wrapper.set_focus()
        import ctypes
        hwnd = ctypes.windll.user32.GetLastActivePopup(main['hwnd'])
        if not self.gui.IsWindowVisible(hwnd):
            hwnd = main['hwnd']
        # Focused file dialogs can be owned popups. Never select unrelated foreground apps.
        focused = self.gui.GetForegroundWindow()
        if self.gui.GetAncestor(focused, 3) == main['hwnd']:
            hwnd = focused
        dialogs = []
        def find_dialog(candidate, _):
            if (self.gui.IsWindowVisible(candidate) and self.gui.IsWindowEnabled(candidate) and self.gui.GetWindowText(candidate) in ('Save As', 'Open')
                    and self.gui.GetAncestor(candidate, 3) == main['hwnd']):
                dialogs.append(candidate)
        self.gui.EnumWindows(find_dialog, None)
        self.gui.EnumChildWindows(main['hwnd'], find_dialog, None)
        dialogs = list(dict.fromkeys(dialogs))
        if len(dialogs) > 1 and hwnd not in dialogs:
            raise RuntimeError('Multiple file dialogs without an active owned popup; observe again')
        if len(dialogs) == 1:
            hwnd = dialogs[0]
        if self.gui.GetAncestor(hwnd, 3) != main['hwnd'] and hwnd != main['hwnd']:
            raise RuntimeError('Unexpected foreground window; refusing to capture or control another application')
        target = self.Application(backend='win32').connect(handle=hwnd).window(handle=hwnd).wrapper_object()
        if self.gui.GetForegroundWindow() != hwnd:
            target.set_focus()
        rectangle = self.gui.GetWindowRect(hwnd)
        controls = []
        for child in target.children()[:60]:
            try:
                controls.append({'text': child.window_text()[:150], 'class': child.class_name(), 'id': child.control_id()})
            except Exception:
                pass
        image = target.capture_as_image()
        if image is None:
            raise RuntimeError('Screenshot unavailable; no input permitted')
        current_rectangle = self.gui.GetWindowRect(hwnd)
        if (current_rectangle != rectangle or image.size != (rectangle[2] - rectangle[0], rectangle[3] - rectangle[1])):
            raise RuntimeError('Window changed during capture; observe again before sending input')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        file_fields = []
        def find_file_field(child, _):
            if self.gui.GetDlgCtrlID(child) == 1148 and self.gui.GetClassName(child) in ('Edit', 'ComboBox', 'ComboBoxEx32'):
                file_fields.append(child)
        self.gui.EnumChildWindows(hwnd, find_file_field, None)
        return {'hwnd': hwnd, 'main_hwnd': main['hwnd'], 'pid': main['pid'], 'file_dialog': bool(file_fields),
                'title': self.gui.GetWindowText(hwnd), 'rectangle': list(rectangle),
                'width': image.width, 'height': image.height, 'controls': controls}, stream.getvalue()

    def verify_target(self, state):
        self.ensure_unlocked()
        if self.api.GetAsyncKeyState(0x1B) & 0x8000:
            raise RuntimeError('Escape is held; worker input stopped')
        if not self.gui.IsWindow(state['hwnd']):
            raise RuntimeError('Window closed; observe again')
        _, pid = self.process.GetWindowThreadProcessId(state['main_hwnd'])
        if pid != state['pid']:
            raise RuntimeError('Report process changed; observe again')
        allowed_foreground = {state['hwnd']}
        if state['title'] in ('Save As', 'Open'):
            allowed_foreground.add(state['main_hwnd'])
        if self.gui.GetForegroundWindow() not in allowed_foreground:
            self.Application(backend='win32').connect(handle=state['hwnd']).window(handle=state['hwnd']).set_focus()
        if self.gui.GetForegroundWindow() not in allowed_foreground or not self.gui.IsWindowEnabled(state['hwnd']):
            raise RuntimeError('A modal or another window blocks the observed target; observe again')
        if list(self.gui.GetWindowRect(state['hwnd'])) != state['rectangle']:
            raise RuntimeError('Window moved; observe again')

    def click(self, state, x, y):
        self.verify_target(state)
        point = (state['rectangle'][0] + x, state['rectangle'][1] + y)
        under = self.gui.WindowFromPoint(point)
        if self.gui.GetAncestor(under, 3) != state['main_hwnd']:
            _, popup_pid = self.process.GetWindowThreadProcessId(under)
            root = self.gui.GetAncestor(under, 2)
            if popup_pid != state['pid'] or self.gui.GetClassName(root) not in ('ComboLBox', '#32768'):
                raise RuntimeError('Point is covered by another application')
        self.mouse.click(coords=point)

    def key(self, state, value):
        self.verify_target(state)
        self.keyboard.send_keys(SHORTCUTS[value], pause=0.05)

    def type_text(self, state, value):
        self.verify_target(state)
        escaped = ''.join('{{}' if c == '{' else '{}}' if c == '}' else '{'+c+'}' if c in '+^%~()' else c for c in value)
        self.keyboard.send_keys(escaped, with_spaces=True, pause=0.02, vk_packet=True)

    def type_file_path(self, state, value):
        self.verify_target(state)
        fields = []
        def visit(child, _):
            if self.gui.GetDlgCtrlID(child) == 1148 and self.gui.GetClassName(child) == 'Edit':
                fields.append(child)
        self.gui.EnumChildWindows(state['hwnd'], visit, None)
        if len(fields) != 1:
            raise RuntimeError('Expected one native filename field; no path entered')
        # Synchronous native control input avoids filename autocomplete dropping keystrokes.
        edit = self.Application(backend='win32').connect(handle=fields[0]).window(handle=fields[0]).wrapper_object()
        edit.set_edit_text(str(value))
        if edit.text_block() != str(value):
            raise RuntimeError('Filename field did not retain the complete path; observe before proceeding')

    def invoke_save(self, main):
        self.ensure_unlocked()
        if not self.gui.IsWindowEnabled(main['hwnd']):
            raise RuntimeError('A modal dialog blocks Desktop Save')
        views = []
        def report_view(child, _):
            if self.gui.GetClassName(child) == 'Chrome_WidgetWin_1' and self.gui.GetWindowText(child) == 'ms-pbi.pbi.microsoft.com/minerva/reportView.html':
                views.append(child)
        self.gui.EnumChildWindows(main['hwnd'], report_view, None)
        if len(views) != 1:
            raise RuntimeError('Expected exactly one enrolled report view for Save')
        _, view_pid = self.process.GetWindowThreadProcessId(views[0])
        if view_pid != main['pid']:
            raise RuntimeError('Report view process changed; no Save invoked')
        # pywinauto.connect(process=...) probes PROCESS_QUERY_INFORMATION.
        # A limited worker can receive Access Denied for a live elevated Desktop,
        # which pywinauto misleadingly reports as ProcessNotFoundError. Bind the
        # already discovered native HWND; keep the exact process/owner checks.
        window = self.Application(backend='uia').connect(handle=views[0]).window(handle=views[0])
        buttons = [button for button in window.descendants(control_type='Button')
                   if button.element_info.automation_id == 'save' and button.is_enabled()]
        if len(buttons) != 1:
            raise RuntimeError('Expected exactly one enabled native Save command')
        buttons[0].iface_invoke.Invoke()


class Worker:
    def __init__(self, config, backend=None):
        self.config, self.backend = config, backend or Win32Backend()
        self.root = Path(config['data_root']).resolve() / 'windows-worker'
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshot = None
        self.launched = {}
        self.lock = threading.RLock()
        targets = self.root / 'targets.json'
        self.release_names = json.loads(targets.read_text()) if targets.exists() else {}

    def project(self, alias):
        project = self.config.get('desktop_reports', {}).get(alias) or self.config.get('authoring_projects', {}).get(alias)
        if not project:
            raise PermissionError('Project is not enrolled')
        return Path(project).resolve()

    def main(self, alias):
        name = self.project(alias).stem
        names = {name, *self.release_names.get(alias, [])}
        windows = self.backend.windows()
        candidates = [w for w in windows if any(
            w['title'] == title or w['title'].startswith(title + ' - ') for title in names)]
        if not candidates and alias in self.launched:
            candidates = [w for w in windows if w['pid'] == self.launched[alias]]
        if len(candidates) != 1:
            raise RuntimeError('Expected exactly one enrolled Power BI report window; found ' + str(len(candidates)))
        return candidates[0]

    def observe(self, project):
        main = self.main(project)
        if not main['title'].strip():
            raise RuntimeError('Desktop is starting; wait, then observe again before sending input')
        state, png = self.backend.capture(main)
        token = uuid.uuid4().hex
        state.update(snapshot_id=token, project=project, created=time.monotonic())
        self.snapshot = state
        path = self.root / (token + '.png')
        path.write_bytes(png)
        metadata = {k: v for k, v in state.items() if k != 'created'}
        metadata['evidence_image'] = str(path)
        return [TextContent(type='text', text=json.dumps(metadata)),
                ImageContent(type='image', mimeType='image/png', data=base64.b64encode(png).decode())]

    def consume(self, token):
        snapshot, self.snapshot = self.snapshot, None
        if not snapshot or snapshot['snapshot_id'] != token or time.monotonic() - snapshot['created'] > 120:
            raise ValueError('Stale or consumed snapshot; observe Desktop first')
        self.backend.verify_target(snapshot)
        return snapshot

    def act(self, token, operation, **args):
        with self.lock:
            state = self.consume(token)
            if operation == 'click':
                x, y = args['x'], args['y']
                if not 0 <= x < state['width'] or not 0 <= y < state['height']:
                    raise ValueError('Click must be within the observed report window')
                self.backend.click(state, x, y)
            elif operation == 'key':
                if args['key'] not in SHORTCUTS:
                    raise ValueError('Shortcut is not allowed')
                self.backend.key(state, args['key'])
            elif operation == 'text':
                value = args['text']
                if not 1 <= len(value) <= 200 or any(c in value for c in '\r\n\x00:/\\'):
                    raise ValueError('Only single-line report text; paths have a separate tool')
                self.backend.type_text(state, value)
            elif operation == 'path':
                # File-name typing is restricted to a visible native Open/Save dialog.
                if not state.get('file_dialog') or not re.search(r'^(Save As|Open)$', state['title'], re.I):
                    raise PermissionError('A native Open or Save As dialog must be observed first')
                path = args['path']
                self.backend.type_file_path(state, str(path))
            else:
                raise ValueError('Unknown operation')
            (self.root / (token + '.audit.json')).write_text(json.dumps({'project': state['project'],
                'operation': operation, 'time': time.time(), 'state': 'input_sent_observe_result'}))
            time.sleep(0.35)  # allow input dispatch before taking evidence; never chain blind actions
            return self.observe(state['project'])


def build(config):
    worker = Worker(config)
    mcp = FastMCP('Power BI Windows Worker')

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def save_report(project: str, expected_sha256: str) -> dict:
        """Save an enrolled working PBIX in place with one native Save invocation.
        No screenshots or coordinate actions are required. Internally uses Windows UIA Invoke,
        not a Power BI save API. Requires an existing desktop_save_targets entry and matching
        disk hash. Backs up first; confirms the exact path, clean state through official Desktop
        Bridge, and PBIX integrity. Never retries an uncertain save or handles Save As dialogs.
        """
        from .desktop_save import DesktopBridge, SaveService
        with worker.lock:
            return SaveService(config, worker, DesktopBridge(config)).save(project, expected_sha256)

    @mcp.tool(annotations={'readOnlyHint': True})
    def get_dashboard_preview(project: str, page_name: str = 'Page 1') -> list[TextContent | ImageContent]:
        """Return a report-page image through the official Desktop Bridge API.
        No screen coordinates, mouse or keyboard are used. Requires the exact enrolled PBIX
        open in Desktop. The image shows current filter state; it is not a Report Server render.
        """
        from .desktop_save import DesktopBridge
        from .core import sha256
        import zipfile
        with worker.lock:
            worker.backend.ensure_unlocked()
            path = Path(config.get('desktop_save_targets', {}).get(project) or worker.project(project)).resolve()
            main = worker.main(project)
            bridge = DesktopBridge(config)
            state = bridge.state(main['pid'])
            if Path(state.get('currentFilePath') or '').resolve() != path or path.suffix.lower() != '.pbix':
                raise PermissionError('Expected the enrolled PBIX to be open')
            pages = []
            with zipfile.ZipFile(path) as archive:
                if 'Report/Layout' in archive.namelist():
                    report = json.loads(archive.read('Report/Layout').decode('utf-16-le'))
                    pages = [{'id': p['name'], 'name': p['displayName']} for p in report['sections']]
                else:
                    for name in archive.namelist():
                        if re.fullmatch(r'Report/definition/pages/[A-Za-z0-9_-]+/page.json', name):
                            page = json.loads(archive.read(name))
                            pages.append({'id': page['name'], 'name': page['displayName']})
            selected = [p for p in pages if p['name'] == page_name]
            if len(selected) != 1:
                raise ValueError('Expected one saved page with that display name')
            directory = Path(config['data_root']) / 'dashboard-previews'
            directory.mkdir(parents=True, exist_ok=True)
            image_path = directory / (uuid.uuid4().hex + '.png')
            result = subprocess.run([bridge.node, str(bridge.cli), 'screenshot', selected[0]['id'],
                '--pid', str(main['pid']), '--output', str(image_path), '--scale', '1', '--wait-seconds', '15'],
                capture_output=True, text=True, encoding='utf-8', timeout=35,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or not image_path.is_file():
                raise RuntimeError('Desktop Bridge preview failed; no UI input sent')
            if image_path.stat().st_size > 20 * 1024 * 1024:
                raise RuntimeError('Preview exceeded the image size limit')
            png = image_path.read_bytes()
            if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise RuntimeError('Desktop Bridge did not return a PNG')
            metadata = {'project': project, 'page': page_name, 'file_name': path.name,
                        'file_sha256': sha256(path), 'source': 'Desktop Bridge API', 'image_path': str(image_path)}
            image_path.with_suffix('.json').write_text(json.dumps(metadata, indent=2))
            return [TextContent(type='text', text=json.dumps(metadata)),
                    ImageContent(type='image', mimeType='image/png', data=base64.b64encode(png).decode())]

    @mcp.tool(annotations={'readOnlyHint': True})
    def desktop_observe(project: str) -> list[TextContent | ImageContent]:
        """Return a screenshot and single-use action token for the enrolled Power BI report.
        Requires unlocked interactive Windows. Inspect the image before every input. The worker
        selects only PBIDesktop.exe and its owned dialogs. Do not operate credentials, deletion,
        access/security, terms, or unknown modal dialogs; stop for operator attention instead.
        """
        with worker.lock:
            return worker.observe(project)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def desktop_open_enrolled_report(project: str) -> dict:
        """Launch only an operator-enrolled PBIX/PBIP in the configured Desktop executable.
        Observe afterwards; opening may take time. Never retry a launch without checking state.
        Does not download, accept terms, authenticate, or open arbitrary paths.
        """
        with worker.lock:
            path = worker.project(project)
            executable = Path(config.get('desktop_executable', ''))
            if not executable.is_file() or executable.name.lower() != 'pbidesktop.exe':
                raise ValueError('Configure the installed PBIDesktop.exe path first')
            if not path.is_file() or path.suffix.lower() not in ('.pbix', '.pbip'):
                raise ValueError('Enrolled report must be an existing PBIX/PBIP')
            if project in worker.launched:
                raise RuntimeError('Launch already attempted in this session; observe before any further action')
            names = {path.stem, *worker.release_names.get(project, [])}
            if any(any(w['title'] == n or w['title'].startswith(n + ' - ') for n in names) for w in worker.backend.windows()):
                raise RuntimeError('Enrolled report is already open; observe it')
            process = subprocess.Popen([str(executable), str(path)], close_fds=True)
            worker.launched[project] = process.pid
            (worker.root / (uuid.uuid4().hex + '.audit.json')).write_text(json.dumps({
                'project': project, 'operation': 'open_enrolled_report', 'pid': process.pid, 'time': time.time()}))
            return {'status': 'launch_requested', 'pid': process.pid, 'project': project, 'next': 'desktop_observe'}

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def desktop_click(snapshot_id: str, x: int, y: int) -> list[TextContent | ImageContent]:
        """Click one control in the last screenshot, then return a fresh screenshot. No blind retries.
        Use for selecting pages/slicers, applying an external reload, and known save controls.
        """
        return worker.act(snapshot_id, 'click', x=x, y=y)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def desktop_press_key(snapshot_id: str, key: str) -> list[TextContent | ImageContent]:
        """Allowed keys: tab, shift_tab, enter, escape, up/down/left/right, space, select_all,
        save, save_as, open, backspace. Inspect focus/dialog before using. No shell/Windows shortcuts.
        """
        return worker.act(snapshot_id, 'key', key=key)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def desktop_type_text(snapshot_id: str, text: str) -> list[TextContent | ImageContent]:
        """Type a report label/search value into the visibly focused field. No paths/URLs/commands.
        """
        return worker.act(snapshot_id, 'text', text=text)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def desktop_type_release_path(snapshot_id: str, file_name: str) -> list[TextContent | ImageContent]:
        """Type a NEW PBIX path in a native Save As dialog, within configured release_root only.
        The agent must first focus and select the file-name field, select PBIX type, then Save.
        Existing files are refused. Verify the resulting file with the report-authoring MCP.
        """
        root = Path(config['release_root']).resolve()
        path = (root / safe_file_name(file_name)).resolve()
        if path.parent != root or path.exists():
            raise ValueError('Use a new file directly inside release_root')
        project = (worker.snapshot or {}).get('project')
        result = worker.act(snapshot_id, 'path', path=path)
        names = worker.release_names.setdefault(project, [])
        if path.stem not in names:
            names.append(path.stem)
        (worker.root / 'targets.json').write_text(json.dumps(worker.release_names, indent=2))
        return result

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def desktop_type_project_path(snapshot_id: str, project: str) -> list[TextContent | ImageContent]:
        """Type the enrolled PBIP path in a native Open dialog after focusing the file-name field.
        Use when reloading externally edited project files; never save a stale in-memory project first.
        """
        return worker.act(snapshot_id, 'path', path=worker.project(project))

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    build(json.loads(Path(args.config).read_text(encoding='utf-8-sig'))).run(transport='stdio')


if __name__ == '__main__':
    main()
