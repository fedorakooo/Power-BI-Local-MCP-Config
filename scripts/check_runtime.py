"""Readiness, upstream read and optional Desktop launch via MCP. No publication."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def progress(args, completed, status):
    if args.progress:
        print('PBIMCP_PROGRESS ' + json.dumps({'completed': completed,
            'total': 4 if args.no_desktop else 5, 'status': status}), flush=True)


async def main(args):
    root = Path(args.root).resolve()
    settings = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    service = root/'services/powerbi-reportserver-mcp'
    sys.path.insert(0, str(service))
    from pbirs_mcp.desktop_save import DesktopBridge
    from pbirs_mcp.windows_worker import Worker
    config = json.loads((service/'config.local.json').read_text(encoding='utf-8-sig'))
    inventory = []
    for name in ('modeling', 'reportserver', 'authoring', 'desktop'):
        progress(args, len(inventory), f'Connecting to {name}')
        url = f"http://127.0.0.1:{settings['frontend_port']}/fedaraka-powerbi-{name}/mcp"
        deadline = time.monotonic()+60
        last_notice = time.monotonic()
        while True:
            try:
                async with streamablehttp_client(url) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = [t.name for t in (await session.list_tools()).tools]
                        if name == 'reportserver':
                            result = await session.call_tool('list_reports', {})
                            if result.isError:
                                raise RuntimeError('Report Server catalog/authentication check failed')
                        if name == 'desktop' and not args.no_desktop:
                            worker = Worker(config)
                            try:
                                main_window = worker.main(settings['project_alias'])
                                state = DesktopBridge(config).state(main_window['pid'])
                                target = Path(config['desktop_reports'][settings['project_alias']]).resolve()
                                if Path(state.get('currentFilePath') or '').resolve() != target:
                                    raise RuntimeError('Same report name is open from a different folder; close it before starting this deployment')
                            except RuntimeError as error:
                                if 'found 0' not in str(error):
                                    raise
                                launched = await session.call_tool('desktop_open_enrolled_report', {'project': settings['project_alias']})
                                if launched.isError:
                                    raise RuntimeError('Desktop launch failed; check unlocked interactive session and configured executable')
                        inventory.append({'server': name, 'url': url, 'tool_count': len(tools)})
                        progress(args, len(inventory), f'{name} ready: {len(tools)} tools')
                        break
            except Exception:
                # Only retry initialization/readiness, never retry Desktop launch.
                if name == 'desktop' or time.monotonic() >= deadline:
                    raise
                if time.monotonic() - last_notice >= 5:
                    progress(args, len(inventory), f'Waiting for {name}; startup deadline in {max(0, int(deadline-time.monotonic()))}s')
                    last_notice = time.monotonic()
                await asyncio.sleep(1)
    if not args.no_desktop:
        progress(args, 4, 'Waiting for Desktop Bridge and enrolled PBIX')
        deadline = time.monotonic()+60
        last_notice = time.monotonic()
        while True:
            try:
                worker = Worker(config)
                window = worker.main(settings['project_alias'])
                state = DesktopBridge(config).state(window['pid'])
                if Path(state.get('currentFilePath') or '').resolve() != Path(config['desktop_reports'][settings['project_alias']]).resolve():
                    raise RuntimeError('Desktop file mismatch')
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Desktop readiness not confirmed; no automatic launch retry') from None
                if time.monotonic() - last_notice >= 5:
                    progress(args, 4, f'Waiting for Desktop Bridge; readiness deadline in {max(0, int(deadline-time.monotonic()))}s')
                    last_notice = time.monotonic()
                await asyncio.sleep(1)
        progress(args, 5, 'Desktop Bridge and enrolled PBIX verified')
    (root/'runtime/last-startup.json').write_text(json.dumps({'services': inventory, 'desktop_requested': not args.no_desktop}, indent=2))
    print(json.dumps({'status': 'ready', 'services': inventory, 'desktop_requested': not args.no_desktop}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True); parser.add_argument('--config', required=True)
    parser.add_argument('--no-desktop', action='store_true')
    parser.add_argument('--progress', action='store_true', help='Emit structured progress for the PowerShell launcher')
    asyncio.run(main(parser.parse_args()))
