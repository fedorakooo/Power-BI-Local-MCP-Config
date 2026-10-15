"""Operator-authorized live rollback/republication test; dedicated staging GUID only."""
import asyncio
import json
import re
import sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pbirs_mcp.core import sha256


async def main():
    previous = json.loads((ROOT/'runtime/staging-publication-evidence.json').read_text())
    publication = next(x for x in previous if x['tool']=='publish_reviewed_pbix')
    if publication['isError'] or publication['arguments']['report'] != 'staging':
        raise RuntimeError('A verified staging publication is required before this recovery test')
    published = json.loads(publication['result'])
    if published['status'] != 'verified': raise RuntimeError('Publication was not verified')
    file_name = publication['arguments']['file_name']
    file = ROOT/'runtime/release'/file_name
    if file.parent != ROOT/'runtime/release' or sha256(file) != published['sha256']:
        raise RuntimeError('Reviewed release changed; refusing recovery test')
    backup = ROOT/'runtime/backups'/(published['backup_id']+'.pbix')
    metadata = json.loads(backup.with_suffix('.json').read_text())
    if metadata['report'] != 'staging' or sha256(backup) != metadata['sha256']:
        raise RuntimeError('Baseline backup mismatch')
    if metadata['sha256'] == published['sha256']:
        raise RuntimeError('Recovery test requires two different artifacts')
    events=[]

    async def approval(action, source, expected):
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','pbirs_mcp.admin',
            'approve','--actor','fedaraka','--report','staging','--action',action,
            '--file',str(source),'--expected-current-sha256',expected,cwd=ROOT,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await process.communicate()
        if process.returncode: raise RuntimeError('Operator approval failed')
        return re.search(r'([0-9a-f]{32})\s*$',stdout.decode())[1]

    async with streamablehttp_client('http://127.0.0.1:8012/fedaraka-powerbi-reportserver/mcp') as (read,write,_):
        async with ClientSession(read,write) as session:
            await session.initialize()
            async def call(tool,args):
                result=await session.call_tool(tool,args)
                values=[x.text for x in result.content if x.type=='text']
                events.append({'tool':tool,'arguments':args,'isError':result.isError,'result':values})
                (ROOT/'runtime/staging-recovery-evidence.json').write_text(json.dumps(events,indent=2))
                if result.isError:
                    if tool in ('restore_previous_pbix','publish_reviewed_pbix'):
                        await call('download_report_backup',{'report':'staging'})
                    raise RuntimeError(tool+' failed; inspect current state; no write retry')
                return [json.loads(x) for x in values]
            reports=await call('list_reports',{})
            stage=next(x for x in reports if x['alias']=='staging')
            if stage['path']!='/Fedaraka MCP Validation/Sales Teams Quarterly Performance':
                raise RuntimeError('Staging path mismatch')
            current=(await call('download_report_backup',{'report':'staging'}))[0]
            if current['sha256']!=published['sha256']: raise RuntimeError('Server changed since review')
            token=await approval('restore',backup,current['sha256'])
            result=(await call('restore_previous_pbix',{'report':'staging','backup_id':published['backup_id'],'approval_id':token}))[0]
            restored=(await call('download_report_backup',{'report':'staging'}))[0]
            if result['status']!='verified' or restored['sha256']!=metadata['sha256']:
                raise RuntimeError('Restore not verified; no subsequent writes')
            print('RESTORE: verified previous PBIX',flush=True)
            token=await approval('publish',file,restored['sha256'])
            result=(await call('publish_reviewed_pbix',{'report':'staging','file_name':file_name,'approval_id':token}))[0]
            final=(await call('download_report_backup',{'report':'staging'}))[0]
            if result['status']!='verified' or final['sha256']!=published['sha256']:
                raise RuntimeError('Final publication not verified')
            await call('get_report_link',{'report':'staging'})
            print('REPUBLISH: verified updated PBIX; final SHA256='+final['sha256'],flush=True)


asyncio.run(main())
