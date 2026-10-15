"""Create one additive, explicitly named demo measure and verify it in Desktop.

No automatic write retries, file saving, refresh, publication or deletion.
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]
NAME = 'Fedaraka MCP Win Rate %'
TABLE = '#Measures'


async def main():
    evidence = []
    verify_only = '--verify-only' in sys.argv
    destination = ROOT / ('runtime/desktop-measure-verification.json' if verify_only else 'runtime/desktop-measure-update.json')
    async with streamablehttp_client('http://127.0.0.1:8012/fedaraka-powerbi-modeling/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, request):
                result = await session.call_tool(tool, {'request': request})
                parsed = [json.loads(x.text) for x in result.content if x.type == 'text']
                evidence.append({'tool': tool, 'request': request, 'isError': result.isError,
                                 'result': parsed, 'raw': result.model_dump(mode='json', exclude_none=True)})
                destination.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
                if result.isError:
                    raise RuntimeError(str(parsed))
                return parsed[0] if parsed else {'acknowledged': True, 'verificationRequired': True}

            instances = (await call('connection_operations', {'operation': 'ListLocalInstances'}))['data']
            if len(instances) != 1 or 'Sales Teams Quarterly Performance' not in json.dumps(instances[0]):
                raise RuntimeError('Expected the single reviewed Sales Teams Quarterly Performance Desktop instance')
            connection = (await call('connection_operations', {
                'operation': 'Connect', 'connectionString': instances[0]['connectionString']}))['data']
            if not isinstance(connection, str):
                connection = connection['connectionName']
            listing = await call('measure_operations', {'operation': 'List', 'connectionName': connection,
                'filter': {'tableNames': [TABLE], 'maxResults': 1000}})
            measures = [m for t in listing.get('data', []) for m in t.get('measures', [])]
            if not verify_only and any(m['name'].casefold() == NAME.casefold() for m in measures):
                raise RuntimeError('Demo measure already exists; refusing to overwrite it')
            required = {'Opportunities Won', 'Opportunities'}
            if not required.issubset({m['name'] for m in measures}):
                raise RuntimeError('Required existing measures are missing')
            definition = {'tableName': TABLE, 'name': NAME,
                'expression': 'DIVIDE([Opportunities Won], [Opportunities], 0)',
                'formatString': '0.00%', 'displayFolder': 'Fedaraka MCP',
                'description': 'Demo KPI created through local MCP by Codex. Won opportunities / all opportunities; responds to report filter context.'}
            if not verify_only:
                created = await call('measure_operations', {'operation': 'Create', 'connectionName': connection,
                    'definitions': [definition], 'options': {'useTransaction': True, 'continueOnError': False}})
                print('CREATE ' + json.dumps(created), flush=True)
            verified = await call('measure_operations', {'operation': 'Get', 'connectionName': connection,
                'references': [{'tableName': TABLE, 'name': NAME}]})
            print('GET ' + json.dumps(verified), flush=True)
            query = 'EVALUATE ROW("Fedaraka Win Rate", [Fedaraka MCP Win Rate %], "Existing Conversion Rate", [Conversion Rate %])'
            values = await call('dax_query_operations', {'operation': 'Execute', 'connectionName': connection,
                'query': query, 'maxRows': 1, 'resultMode': 'Inline', 'timeoutSeconds': 30})
            rows = values.get('data', {}).get('rows', [])
            if len(rows) != 1 or abs(rows[0]['[Fedaraka Win Rate]'] - rows[0]['[Existing Conversion Rate]']) > 1e-10:
                raise RuntimeError('Verification failed; inspect the evidence, do not retry the write')
            print('DAX_VERIFIED ' + json.dumps(values), flush=True)
            print('Created and verified ' + TABLE + '[' + NAME + ']. Desktop PBIX has not been saved.', flush=True)
            print('Evidence: ' + str(destination), flush=True)


asyncio.run(main())
