"""Verify native Codex MCP discovery without starting an agent or contacting STAIR."""
import asyncio
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def main():
    executable = shutil.which('codex')
    if not executable:
        raise RuntimeError('Codex CLI not found')
    with (ROOT / 'runtime/codex-mcp-check.stderr.log').open('wb') as log:
        process = await asyncio.create_subprocess_exec(
            executable, 'app-server', '--stdio',
            '-c', 'mcp_servers.stair_platform.enabled=false',
            '-c', 'mcp_servers.node_repl.enabled=false',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log,
        )
        counter = 0

        async def request(method, params):
            nonlocal counter
            counter += 1
            process.stdin.write((json.dumps({'id': counter, 'method': method, 'params': params}) + '\n').encode())
            await process.stdin.drain()
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=60)
                if not line:
                    raise RuntimeError('Codex app-server exited; inspect private stderr log')
                response = json.loads(line)
                if response.get('id') == counter:
                    if 'error' in response:
                        raise RuntimeError(str(response['error']))
                    return response['result']

        try:
            await request('initialize', {'clientInfo': {'name': 'powerbi-local-check', 'version': '0.1.0'}})
            process.stdin.write(b'{"method":"initialized"}\n')
            await process.stdin.drain()
            inventory = []
            for name in ['powerbi_modeling_local', 'powerbi_reportserver_local', 'powerbi_reportauthoring_local', 'powerbi_desktop_local']:
                result = await request('mcpServerStatus/list', {'serverName': name, 'detail': 'toolsAndAuthOnly'})
                entries = result.get('data', [])
                for entry in entries:
                    tools = entry.get('tools', {})
                    item = {'name': entry.get('name'), 'toolCount': len(tools),
                            'tools': list(tools) if isinstance(tools, dict) else tools}
                    inventory.append(item)
                    print(json.dumps(item), flush=True)
                if not entries or not any(entry.get('tools') for entry in entries):
                    raise RuntimeError('No tools discovered for ' + name)
            (ROOT / 'runtime/codex-mcp-inventory.json').write_text(json.dumps(inventory, indent=2))
            print('Native Codex discovery of all four local MCP servers: PASS', flush=True)
        finally:
            process.terminate()
            await process.wait()


asyncio.run(main())
