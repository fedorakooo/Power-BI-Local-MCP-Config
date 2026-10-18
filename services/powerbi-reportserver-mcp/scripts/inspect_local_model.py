"""Read-only Desktop inspection through the same local HTTP endpoint configured in Codex."""
import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    evidence = []
    async with streamablehttp_client('http://127.0.0.1:8012/stair-powerbi-modeling/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, request):
                result = await session.call_tool(tool, {'request': request})
                blocks = [x.text for x in result.content if x.type == 'text']
                parsed = [json.loads(x) for x in blocks]
                evidence.append({'tool': tool, 'request': request, 'isError': result.isError, 'result': parsed})
                if result.isError:
                    raise RuntimeError(str(parsed))
                return parsed[0]

            discovered = await call('connection_operations', {'operation': 'ListLocalInstances'})
            instances = discovered.get('data', [])
            if len(instances) != 1:
                print(json.dumps({'status': 'target_selection_required', 'instances': instances}, indent=2))
                return
            connected = await call('connection_operations', {
                'operation': 'Connect', 'connectionString': instances[0]['connectionString']})
            connections = await call('connection_operations', {'operation': 'ListConnections'})
            data = connected.get('data', {})
            connection_name = data if isinstance(data, str) else data.get('connectionName')
            if not connection_name:
                raise RuntimeError('Expected explicit connectionName in Connect result')
            for tool in ['table_operations', 'measure_operations']:
                result = await call(tool, {'operation': 'List', 'connectionName': connection_name})
                rows = result.get('data', [])
                if tool == 'measure_operations':
                    rows = [m for table in rows for m in table.get('measures', [])]
                print(tool + ': ' + json.dumps({'message': result.get('message'), 'sample': rows[:5]}))
            query = ('EVALUATE ROW("Sales Won", [Sales Won], "Sales", [Sales], '
                     '"Opportunities", [Opportunities], "Opportunities Won", [Opportunities Won], '
                     '"Conversion Rate", [Conversion Rate %], '
                     '"Avg Sales per Won Opportunity", [Avg Sales per Won Opportunity])')
            result = await call('dax_query_operations', {
                'operation': 'Execute', 'connectionName': connection_name, 'query': query,
                'maxRows': 1, 'timeoutSeconds': 30, 'resultMode': 'Inline'})
            print('DAX_AGGREGATES ' + json.dumps(result))
    async with streamablehttp_client('http://127.0.0.1:8012/stair-powerbi-reportserver/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool, args in [('list_reports', {}), ('get_report_link', {'report': 'sales'}),
                               ('download_report_backup', {'report': 'sales'})]:
                result = await session.call_tool(tool, args)
                parsed = [json.loads(x.text) for x in result.content if x.type == 'text']
                evidence.append({'tool': tool, 'request': args, 'isError': result.isError, 'result': parsed})
                print(tool + ' ' + json.dumps(parsed))
                if result.isError:
                    raise RuntimeError(tool + ' failed')
    destination = ROOT / 'runtime/local-desktop-inspection.json'
    destination.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print('Evidence saved: ' + str(destination))


asyncio.run(main())
