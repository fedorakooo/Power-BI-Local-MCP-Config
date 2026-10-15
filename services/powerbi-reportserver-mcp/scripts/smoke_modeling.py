import asyncio
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[1]
    binaries = list((root / 'modeling/node_modules/.pnpm').rglob('powerbi-modeling-mcp.exe'))
    if len(binaries) != 1:
        raise RuntimeError('Expected exactly one installed Microsoft modeling binary')
    params = StdioServerParameters(command=str(binaries[0]), args=['--start', '--readonly', '--accepteula'], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            print('Microsoft modeling MCP handshake: PASS; tool count=' + str(len(listing.tools)))
            result = await session.call_tool('connection_operations', {'request': {'operation': 'ListLocalInstances'}})
            print('Local instance discovery isError=' + str(result.isError))
            for block in result.content:
                if block.type == 'text':
                    print(block.text[:1600])


if __name__ == '__main__':
    asyncio.run(main())
