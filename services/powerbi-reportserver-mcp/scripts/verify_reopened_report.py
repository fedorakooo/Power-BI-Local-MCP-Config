"""Read-only persistence check of the dedicated saved Report Server PBIX via MCP."""
import asyncio
import json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT=Path(__file__).resolve().parents[1]


async def main():
    events=[]
    async with streamablehttp_client('http://127.0.0.1:8012/fedaraka-powerbi-modeling/mcp') as (read,write,_):
        async with ClientSession(read,write) as session:
            await session.initialize()
            async def call(tool,request):
                result=await session.call_tool(tool,{'request':request})
                parsed=[json.loads(x.text) for x in result.content if x.type=='text']
                events.append({'tool':tool,'request':request,'isError':result.isError,'result':parsed})
                (ROOT/'runtime/reopened-report-evidence.json').write_text(json.dumps(events,indent=2))
                if result.isError:raise RuntimeError(tool+' failed')
                return parsed[0]
            instances=(await call('connection_operations',{'operation':'ListLocalInstances'}))['data']
            matching=[x for x in instances if x.get('parentWindowTitle')=='Fedaraka Server Automated - Power BI Desktop (September 2026)']
            if len(matching)!=1:raise RuntimeError('Expected one exact enrolled report instance')
            connection=(await call('connection_operations',{'operation':'Connect','connectionString':matching[0]['connectionString']}))['data']
            if not isinstance(connection,str):connection=connection['connectionName']
            await call('measure_operations',{'operation':'Get','connectionName':connection,
                'references':[{'tableName':'#Measures','name':'Fedaraka MCP Win Rate %'}]})
            query='EVALUATE ROW("All Managers", [Fedaraka MCP Win Rate %], "Cara Losch", CALCULATE([Fedaraka MCP Win Rate %], dim_SaleTeams[manager] = "Cara Losch"))'
            result=await call('dax_query_operations',{'operation':'Execute','connectionName':connection,
                'query':query,'maxRows':1,'resultMode':'Inline','timeoutSeconds':30})
            row=result['data']['rows'][0]
            if abs(row['[All Managers]']-4238/8800)>1e-10 or abs(row['[Cara Losch]']-480/964)>1e-10:
                raise RuntimeError('Persisted ratio/filter verification failed')
            print('Reopened PBIX: persisted measure and filter-context DAX PASS '+json.dumps(row),flush=True)


asyncio.run(main())
