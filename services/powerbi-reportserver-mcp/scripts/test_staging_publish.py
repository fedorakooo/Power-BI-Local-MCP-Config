"""Operator-run, one-attempt publish test restricted to the dedicated validation folder.

Never expose this operator approval helper as an MCP tool. It is authorized only
for this local end-to-end staging test, not for automatic production approvals.
"""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    file_name = sys.argv[1] if len(sys.argv) > 1 else 'STAIR Automated.pbix'
    if Path(file_name).name != file_name or not file_name.endswith('.pbix'):
        raise ValueError('Use a release filename, not a path')
    events = []
    async with streamablehttp_client('http://127.0.0.1:8012/stair-powerbi-reportserver/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                result = await session.call_tool(name, args)
                blocks = [x.text for x in result.content if x.type == 'text']
                body = json.dumps([json.loads(x) for x in blocks]) if name == 'list_reports' and not result.isError else '\n'.join(blocks)
                events.append({'tool': name, 'arguments': args, 'isError': result.isError, 'result': body})
                (ROOT / 'runtime/staging-publication-evidence.json').write_text(json.dumps(events, indent=2))
                return result.isError, body

            error, body = await call('list_reports', {})
            if error:
                raise RuntimeError(body)
            items = json.loads(body)
            stage = next(x for x in items if x['alias'] == 'staging')
            if stage['path'] != '/STAIR MCP Validation/Sales Teams Quarterly Performance':
                raise RuntimeError('Staging target mismatch; refusing to approve or publish')
            error, body = await call('download_report_backup', {'report': 'staging'})
            if error:
                raise RuntimeError(body)
            backup = json.loads(body)
            command = await asyncio.create_subprocess_exec(sys.executable, '-m', 'pbirs_mcp.admin',
                'approve', '--actor', 'stair', '--report', 'staging', '--action', 'publish',
                '--file', str(ROOT / 'runtime/release' / file_name),
                '--expected-current-sha256', backup['sha256'], cwd=ROOT,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await command.communicate()
            if command.returncode:
                raise RuntimeError(stderr.decode())
            approval = re.search(r'([0-9a-f]{32})\s*$', stdout.decode())[1]
            error, body = await call('publish_reviewed_pbix', {'report': 'staging',
                'file_name': file_name, 'approval_id': approval})
            print('PUBLISH isError=' + str(error) + ' ' + body, flush=True)
            if not error and json.loads(body).get('status') != 'verified':
                error = True
            # Always inspect actual state after an attempted write; never retry it.
            check_error, current = await call('download_report_backup', {'report': 'staging'})
            print('AFTER ' + current, flush=True)
            if not check_error:
                expected = hashlib.sha256((ROOT / 'runtime/release' / file_name).read_bytes()).hexdigest()
                check_error = json.loads(current)['sha256'] != expected
            await call('get_report_link', {'report': 'staging'})
            if error or check_error:
                raise RuntimeError('Staging publish did not pass; inspect evidence before any further write')


asyncio.run(main())
