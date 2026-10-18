"""Exercise the report-authoring MCP on the enrolled demo project."""
import asyncio
import json
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    events = []
    params = StdioServerParameters(command=sys.executable, args=['-m', 'pbirs_mcp.report_authoring',
        '--config', str(ROOT / 'config.local.json')], cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                result = await session.call_tool(name, args)
                text = '\n'.join(b.text for b in result.content if b.type == 'text')
                events.append({'tool': name, 'arguments': args, 'isError': result.isError, 'result': text})
                (ROOT / 'runtime/authoring-demo-evidence.json').write_text(json.dumps(events, indent=2))
                if result.isError:
                    raise RuntimeError(text)
                return json.loads(text)

            state = await call('inspect_report_project', {'project': 'sales-demo'})
            if '--dashboard-only' not in sys.argv:
                result = await call('add_project_ratio_measure', {'project': 'sales-demo',
                    'expected_revision': state['revision'], 'table': '#Measures',
                    'measure_name': 'STAIR MCP Win Rate %', 'numerator_measure': 'Opportunities Won',
                    'denominator_measure': 'Opportunities'})
                print(json.dumps(result), flush=True)
                state = await call('inspect_report_project', {'project': 'sales-demo'})
            result = await call('add_kpi_dashboard', {'project': 'sales-demo', 'expected_revision': state['revision'],
                'title': 'STAIR MCP', 'cards': [
                    {'table': '#Measures', 'measure': 'Sales Won', 'title': 'Sales won'},
                    {'table': '#Measures', 'measure': 'Opportunities', 'title': 'Opportunities'},
                    {'table': '#Measures', 'measure': 'STAIR MCP Win Rate %', 'title': 'STAIR win rate'}],
                'slicer_table': 'dim_SaleTeams', 'slicer_column': 'manager'})
            print(json.dumps(result), flush=True)


asyncio.run(main())
