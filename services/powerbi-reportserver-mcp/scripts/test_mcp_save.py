"""One authorized model edit and one high-level MCP save against the dedicated working copy."""
import asyncio
import hashlib
import json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    events = []
    async with streamablehttp_client('http://127.0.0.1:8012/fedaraka-powerbi-modeling/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            async def call(tool, request):
                result = await session.call_tool(tool, {'request': request})
                parsed = [json.loads(x.text) for x in result.content if x.type == 'text']
                events.append({'tool': tool, 'request': request, 'isError': result.isError, 'result': parsed})
                (ROOT / 'runtime/high-level-save-evidence.json').write_text(json.dumps(events, indent=2))
                if result.isError:
                    raise RuntimeError(tool + ' failed; inspect evidence before another write')
                return parsed[0] if parsed else {}
            instances = (await call('connection_operations', {'operation': 'ListLocalInstances'}))['data']
            selected = [x for x in instances if x.get('parentWindowTitle') == 'Fedaraka Server Automated - Power BI Desktop (September 2026)']
            if len(selected) != 1:
                raise RuntimeError('Expected the exact dedicated Server Automated Desktop instance')
            connected = (await call('connection_operations', {'operation': 'Connect', 'connectionString': selected[0]['connectionString']}))['data']
            connection = connected if isinstance(connected, str) else connected['connectionName']
            listing = await call('measure_operations', {'operation': 'List', 'connectionName': connection,
                'filter': {'tableNames': ['#Measures'], 'maxResults': 1000}})
            existing = [m['name'] for table in listing['data'] for m in table.get('measures', [])]
            if 'Fedaraka MCP Win Rate %' in existing:
                raise RuntimeError('Measure already exists; refusing to repeat the mutation')
            await call('measure_operations', {'operation': 'Create', 'connectionName': connection,
                'definitions': [{'tableName': '#Measures', 'name': 'Fedaraka MCP Win Rate %',
                    'expression': 'DIVIDE([Opportunities Won], [Opportunities], 0)',
                    'formatString': '0.00%', 'displayFolder': 'Fedaraka MCP'}],
                'options': {'useTransaction': True, 'continueOnError': False}})
            await call('measure_operations', {'operation': 'Get', 'connectionName': connection,
                'references': [{'tableName': '#Measures', 'name': 'Fedaraka MCP Win Rate %'}]})
    file = ROOT / 'runtime/release/Fedaraka Server Automated.pbix'
    before = hashlib.sha256(file.read_bytes()).hexdigest()
    async with streamablehttp_client('http://127.0.0.1:8012/fedaraka-powerbi-desktop/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('save_report', {'project': 'rs-automation', 'expected_sha256': before})
            events.append({'tool': 'save_report', 'isError': result.isError, 'result': result.model_dump(mode='json')})
            (ROOT / 'runtime/high-level-save-evidence.json').write_text(json.dumps(events, indent=2))
            for item in result.content:
                if item.type == 'text': print(item.text, flush=True)
            if result.isError:
                raise RuntimeError('MCP save failed; inspect state before another invocation')


asyncio.run(main())
