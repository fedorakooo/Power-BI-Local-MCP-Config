"""Create disabled STAIR toolset drafts from locally verified tools, without secrets."""
import asyncio
import json
import zipfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]
MODELING = {'connection_operations', 'database_operations', 'model_operations',
            'table_operations', 'column_operations', 'relationship_operations',
            'measure_operations', 'dax_query_operations', 'transaction_operations'}


async def main():
    records = []
    for name, label in [('modeling', 'Modeling'), ('reportserver', 'Report Server')]:
        async with streamablehttp_client(
            f'http://127.0.0.1:8012/fedaraka-powerbi-{name}/mcp',
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                schemas = [t.model_dump(mode='json', exclude_none=True) for t in response.tools
                           if name != 'modeling' or t.name in MODELING]
        records.append({
            'name': f"Fedaraka's Power BI {label}",
            'description': "Fedaraka's personal Windows Power BI pilot. Locally verified schemas; "
                           "STAIR network connectivity pending. Do not enable until remote discovery succeeds.",
            'overview': ("Inspect and change Desktop semantic models after explicit approval. "
                         "Cannot edit visuals or save Desktop PBIX." if name == 'modeling' else
                         "List authorized reports, return links, back up, publish reviewed saved PBIX, "
                         "and restore. Publishing and restore require an operator-issued one-use approval."),
            'mcpBaseUrl': f'http://report-server.example.com:8012/fedaraka-powerbi-{name}/mcp',
            'enabled': False, 'stateful': True, 'authMode': 'NONE',
            'settings': {}, 'tools': schemas, 'tags': ['fedaraka', 'powerbi'],
        })
    destination = ROOT / 'runtime/fedaraka-stair-toolsets.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('tool_sets_data.json', json.dumps(records))
    print('Created disabled toolset bundle without credentials: ' + str(destination))


asyncio.run(main())
