"""Bounded read-only server checks, independent of an interactive Desktop."""
import argparse
import asyncio
import json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def probe(root):
    config = json.loads((root/'deployment.local.json').read_text(encoding='utf-8-sig'))
    base = f"http://127.0.0.1:{config['frontend_port']}/stair-powerbi-"
    results = []
    for name in ('modeling', 'reportserver', 'authoring', 'headless'):
        async with asyncio.timeout(30):
            async with streamablehttp_client(base+name+'/mcp') as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    if not tools:
                        raise RuntimeError(f'{name}: empty tool list')
                    if name == 'reportserver':
                        result = await session.call_tool('list_reports', {})
                        if result.isError:
                            raise RuntimeError('Report Server catalog check failed')
                    results.append({'server': name, 'tools': len(tools)})
    print(json.dumps({'status': 'background_ready', 'services': results}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    try:
        asyncio.run(probe(parser.parse_args().root))
    except Exception:
        print(json.dumps({'status': 'background_unavailable'}))
        raise SystemExit(1)
