"""Persistent MCP test client for the standalone Windows worker; no LLM or STAIR involved."""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'pbirs_mcp.windows_worker',
        '--config', str(ROOT / 'config.local.json')], cwd=str(ROOT), env=dict(os.environ))
    transport = streamablehttp_client('http://127.0.0.1:8012/stair-powerbi-desktop/mcp') if '--http' in sys.argv else stdio_client(params)
    async with transport as streams:
        read, write = streams[:2]
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(json.dumps({'ready': True, 'tools': [t.name for t in (await session.list_tools()).tools]}), flush=True)
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line or line.strip() == 'quit':
                    break
                request = json.loads(line)
                result = await session.call_tool(request['tool'], request.get('arguments', {}))
                output = []
                for item in result.content:
                    if item.type == 'text':
                        output.append({'text': item.text})
                    elif item.type == 'image':
                        image = ROOT / 'runtime/worker-probe.png'
                        image.write_bytes(base64.b64decode(item.data))
                        output.append({'image': str(image)})
                response = {'isError': result.isError, 'output': output}
                (ROOT / 'runtime/worker-probe-last.json').write_text(json.dumps(response, indent=2))
                compact = dict(response)
                compact['output'] = []
                for item in output:
                    if 'text' in item:
                        try:
                            data = json.loads(item['text'])
                            data.pop('controls', None)
                            compact['output'].append(data)
                        except ValueError:
                            compact['output'].append(item)
                    else:
                        compact['output'].append(item)
                print(json.dumps(compact), flush=True)


asyncio.run(main())
