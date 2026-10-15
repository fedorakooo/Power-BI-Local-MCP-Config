"""Verify the saved PBIX through the report-authoring MCP."""
import asyncio
import json
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'pbirs_mcp.report_authoring',
        '--config', str(ROOT / 'config.local.json')], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('verify_saved_report', {'file_name': 'Fedaraka Automated.pbix'})
            (ROOT / 'runtime/saved-release-verification.json').write_text(result.model_dump_json(indent=2))
            for item in result.content:
                if item.type == 'text':
                    print(item.text)
            if result.isError:
                raise RuntimeError('Saved release verification failed')


asyncio.run(main())
