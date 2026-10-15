import asyncio
import json
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    root = Path(__file__).resolve().parents[1]
    for name in ('modeling', 'reportserver'):
        url = f'http://127.0.0.1:8012/fedaraka-powerbi-{name}/mcp'
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(name + ': tool discovery PASS; count=' + str(len(tools.tools)))
                if name == 'reportserver':
                    result = await session.call_tool('list_reports', {})
                    assert not result.isError
                    print('Report Server catalog call PASS')
                else:
                    result = await session.call_tool('connection_operations', {'request': {'operation': 'ListLocalInstances'}})
                    assert not result.isError
                    instance = json.loads(result.content[0].text)['data'][0]
                    result = await session.call_tool('connection_operations', {'request': {
                        'operation': 'Connect', 'connectionString': instance['connectionString']}})
                    assert not result.isError
                    result = await session.call_tool('connection_operations', {'request': {'operation': 'ListConnections'}})
                    assert not result.isError
                    print('Desktop discovery + Connect + persistent ListConnections PASS')
    print('Both endpoints work without API keys on the allowed network: PASS')


asyncio.run(main())
