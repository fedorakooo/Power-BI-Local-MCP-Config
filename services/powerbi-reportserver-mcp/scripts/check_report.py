"""Read-only live checks and a private backup through the deployed MCP."""
import asyncio
import json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config.local.json').read_text(encoding='utf-8-sig'))
    token = (Path(config['data_root']) / 'operator-token.txt').read_text()
    async with streamablehttp_client('http://127.0.0.1:8010/mcp', headers={'Authorization': 'Bearer ' + token}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool, args in [('list_reports', {}), ('get_report_link', {'report': 'sales'}), ('download_report_backup', {'report': 'sales'})]:
                response = await session.call_tool(tool, args)
                print(tool + ' isError=' + str(response.isError))
                for block in response.content:
                    if block.type == 'text':
                        print(block.text)
                if response.isError:
                    raise RuntimeError('Live check failed: ' + tool)
            denied = await session.call_tool('publish_reviewed_pbix', {
                'report': 'sales', 'file_name': 'Sales Teams Quarterly Performance.pbix', 'approval_id': 'missing-approval'})
            assert denied.isError
            assert any(getattr(block, 'text', '').find('Valid operator approval required') >= 0 for block in denied.content)
            print('Live publication without approval: DENIED as expected; no upload attempted')


if __name__ == '__main__':
    asyncio.run(main())
