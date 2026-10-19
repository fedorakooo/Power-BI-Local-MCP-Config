"""One MCP save operation: scoped UIA Save invocation, official Bridge verification."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path

from .core import sha256


class DesktopBridge:
    def __init__(self, config):
        root = Path(__file__).resolve().parents[1]
        self.cli = root / 'bridge/node_modules/@microsoft/powerbi-desktop-bridge-cli/dist/cli.js'
        paths = Path(config['data_root']) / 'gateway-paths.json'
        self.node = json.loads(paths.read_text(encoding='utf-8-sig'))['node']

    def state(self, pid):
        result = subprocess.run([self.node, str(self.cli), 'status', '--pid', str(pid)],
            capture_output=True, text=True, encoding='utf-8', timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError('Desktop Bridge status failed; no save confirmation available')
        data = json.loads(result.stdout)
        instances = [x for x in data.get('instances', []) if x.get('pid') == pid and x.get('bridgeStatus') == 'connected']
        if len(instances) != 1:
            raise RuntimeError('Expected the exact enrolled Desktop Bridge instance')
        return instances[0]

    @staticmethod
    def model_engine_pids(pid):
        """Correlate only msmdsrv children of the verified enrolled Desktop PID.

        Modeling MCP runs in a background session and may not see window titles.
        Empty/failed discovery is explicitly unavailable, never a guessed port.
        """
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError('Expected a positive Desktop process ID')
        command = (f'Get-CimInstance Win32_Process -Filter "Name=\'msmdsrv.exe\' AND ParentProcessId={pid}" '
                   '| Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress')
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                capture_output=True, text=True, encoding='utf-8', timeout=15,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or not result.stdout.strip():
                return []
            values = json.loads(result.stdout)
            values = values if isinstance(values, list) else [values]
            if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in values):
                return []
            return sorted(set(values))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []


class SaveService:
    def __init__(self, config, worker, bridge):
        self.config, self.worker, self.bridge = config, worker, bridge
        self.root = Path(config['data_root']) / 'desktop-backups'
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_pbix(path):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if archive.testzip() or ('DataModel' not in names and 'Connections' not in names):
                raise ValueError('Saved artifact is not a valid PBIX')
            if 'Report/Layout' not in names and 'Report/definition/version.json' not in names:
                raise ValueError('Saved artifact has no report definition')

    def save(self, project, expected_sha256):
        target = self.config.get('desktop_save_targets', {}).get(project)
        if not target:
            raise PermissionError('Report is not enrolled for in-place Desktop saving')
        path = Path(target).resolve()
        release = Path(self.config['release_root']).resolve()
        if not path.is_relative_to(release) or path.suffix.lower() != '.pbix' or not path.is_file():
            raise PermissionError('Save target must be an existing PBIX inside release_root')
        main = self.worker.main(project)
        lock = self.root / ('save-' + str(main['pid']) + '.lock')
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError('Another save is active or needs operator recovery; no save attempted') from None
        os.close(descriptor)
        try:
            self.worker.backend.ensure_unlocked()
            state = self.bridge.state(main['pid'])
            current = state.get('currentFilePath')
            if not current or Path(current).resolve() != path:
                raise PermissionError('Desktop has a different file open; no save attempted')
            if not isinstance(state.get('hasUnsavedChanges'), bool):
                raise RuntimeError('Desktop Bridge returned an unknown dirty state')
            digest = sha256(path)
            if digest != expected_sha256:
                raise ValueError('PBIX changed since inspection; no save attempted')
            self.validate_pbix(path)
            # A clean Desktop state is verified below as an already-saved artifact;
            # dirty reports use one Save invocation and require observable file I/O.
            before_mtime = path.stat().st_mtime_ns
            backup_id = uuid.uuid4().hex
            backup = self.root / (backup_id + '.pbix')
            shutil.copyfile(path, backup)
            if sha256(backup) != digest:
                raise RuntimeError('Backup verification failed; no save attempted')
            audit = self.root / (backup_id + '.json')
            details = {'project': project, 'pid': main['pid'], 'source': str(path),
                       'before_sha256': digest, 'backup_id': backup_id, 'time': time.time(),
                       'status': 'save_preflight_complete'}
            audit.write_text(json.dumps(details, indent=2))
            # A clean PBIX already on disk needs no UI Save command. On Desktop RS
            # the Save button is disabled in this state, which made UIA report zero
            # enabled commands and incorrectly label a harmless no-op as uncertain.
            if state['hasUnsavedChanges'] is False:
                try:
                    confirmed = self.bridge.state(main['pid'])
                    clean = (Path(confirmed.get('currentFilePath') or '').resolve() == path
                             and confirmed.get('hasUnsavedChanges') is False
                             and sha256(path) == digest)
                except Exception as error:
                    clean = False
                    diagnostic = str(error)[:500]
                else:
                    diagnostic = 'Desktop clean state or PBIX hash changed during verification'
                if clean:
                    result = {'status': 'saved_verified', 'file_name': path.name,
                              'sha256': digest, 'before_sha256': digest,
                              'backup_id': backup_id, 'has_unsaved_changes': False,
                              'save_invocation_method': 'already_saved', 'save_invocations': 0}
                    details.update(result)
                    audit.write_text(json.dumps(details, indent=2))
                    return result
                details.update(status='save_not_invoked', failure_type='RuntimeError',
                               diagnostic=diagnostic)
                audit.write_text(json.dumps(details, indent=2))
                raise RuntimeError('Clean PBIX could not be reverified; no Save invoked')
            details.update(status='save_invocation_pending')
            audit.write_text(json.dumps(details, indent=2))
            try:
                save_method = self.worker.backend.invoke_save(main)  # exactly once; never retry an uncertain write
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    time.sleep(0.75)
                    try:
                        after = self.bridge.state(main['pid'])
                    except RuntimeError:
                        # Save can temporarily make the bridge busy/unavailable.
                        # Retry only this read; the Save command is never repeated.
                        continue
                    if Path(after.get('currentFilePath') or '').resolve() != path:
                        raise RuntimeError('Desktop changed file during save')
                    if after.get('hasUnsavedChanges') is False and path.stat().st_mtime_ns != before_mtime:
                        self.validate_pbix(path)
                        result = {'status': 'saved_verified', 'file_name': path.name,
                                  'sha256': sha256(path), 'before_sha256': digest,
                                  'backup_id': backup_id, 'has_unsaved_changes': False,
                                  'save_invocation_method': save_method, 'save_invocations': 1}
                        details.update(result)
                        audit.write_text(json.dumps(details, indent=2))
                        return result
                raise RuntimeError('Desktop did not confirm save before timeout')
            except Exception as error:
                details['status'] = 'save_outcome_uncertain'
                details['failure_type'] = type(error).__name__
                details['diagnostic'] = str(error)[:500]
                audit.write_text(json.dumps(details, indent=2))
                raise RuntimeError('Save outcome uncertain; inspect state before another invocation. Backup: ' + backup_id) from None
        finally:
            lock.unlink()
