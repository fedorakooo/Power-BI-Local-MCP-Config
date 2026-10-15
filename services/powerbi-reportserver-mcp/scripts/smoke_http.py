"""Test the real deployed local MCP without exposing the token."""
import asyncio
import json
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config.local.json').read_text(encoding='utf-8-sig'))
    token = (Path(config['data_root']) / 'operator-token.txt').read_text()
    async with httpx.AsyncClient() as client:
        assert (await client.get('http://127.0.0.1:8010/health')).status_code == 200
        assert (await client.post('http://127.0.0.1:8010/mcp', json={})).status_code == 401
    async with streamablehttp_client('http://127.0.0.1:8010/mcp', headers={'Authorization': 'Bearer ' + token}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            expected = {'list_reports', 'get_report_link', 'download_report_backup', 'publish_reviewed_pbix', 'restore_previous_pbix'}
            assert {t.name for t in tools.tools} == expected
            response = await session.call_tool('list_reports', {})
            assert not response.isError
            print('HTTP MCP handshake, authentication rejection, five tool schemas and list_reports: PASS')


if __name__ == '__main__':
    asyncio.run(main())
