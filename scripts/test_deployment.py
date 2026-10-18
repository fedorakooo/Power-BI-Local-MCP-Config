import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from configure_deployment import configure


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'relocated folder with spaces'
        self.service = self.root/'services/powerbi-reportserver-mcp'
        for folder, name, version in [('modeling','@microsoft/powerbi-modeling-mcp','1.0.0'),('gateway','supergateway','4.1.0'),('bridge','@microsoft/powerbi-desktop-bridge-cli','1.0.0')]:
            directory=self.service/folder; directory.mkdir(parents=True)
            (directory/'package.json').write_text(json.dumps({'dependencies':{name:version}}))
            (directory/'pnpm-lock.yaml').write_text('lockfileVersion: 9.0')
        binary=self.service/'modeling/node_modules/.pnpm/mock/dist/powerbi-modeling-mcp.exe'
        binary.parent.mkdir(parents=True); binary.touch()
        (self.root/'reports').mkdir()
        with zipfile.ZipFile(self.root/'reports/demo.pbix','w') as archive:
            archive.writestr('Report/Layout','{}'); archive.writestr('DataModel','test')
        self.node=self.root/'node.exe'; self.node.touch()
        self.settings={'portal':'http://server/Reports','frontend_port':10012,
            'allowed_addresses':['127.0.0.1'],'report_alias':'staging',
            'report_id':'11111111-1111-4111-8111-111111111111','project_alias':'demo',
            'report_file':'reports/demo.pbix','desktop_executable':'PBIDesktop.exe','enable_publication':True}
        self.path=self.root/'settings.json'; self.write()
    def write(self):self.path.write_text(json.dumps(self.settings))
    def test_validation_does_not_create_runtime(self):
        configure(self.root,self.path,'',True)
        self.assertFalse((self.service/'runtime').exists())
        self.assertFalse((self.service/'config.local.json').exists())
    def test_relocation_ports_and_client_config(self):
        configure(self.root,self.path,str(self.node))
        config=json.loads((self.service/'config.local.json').read_text())
        self.assertEqual(Path(config['release_root']),self.service/'runtime/release')
        manifest=json.loads((self.service/'gateway/servers.local.json').read_text())
        self.assertEqual([x['port'] for x in manifest['mcpServers'].values()],[10013,10014,10015,10016])
        self.assertIn(':10012',(self.service/'gateway/Caddyfile').read_text())
        self.assertIn('enabled_tools',(self.root/'generated/codex-mcp.toml').read_text())
    def test_repeat_setup_preserves_edited_working_report(self):
        configure(self.root,self.path,str(self.node))
        working=self.service/'runtime/release/demo.pbix'; working.write_bytes(b'edited-working-report')
        configure(self.root,self.path,str(self.node))
        self.assertEqual(working.read_bytes(),b'edited-working-report')
    def test_public_network_and_source_escape_rejected(self):
        self.settings['allowed_addresses']=['0.0.0.0/0']; self.write()
        with self.assertRaises(ValueError):configure(self.root,self.path,'',True)
        self.settings['allowed_addresses']=['127.0.0.1']; self.settings['report_file']='../outside.pbix'; self.write()
        with self.assertRaises(ValueError):configure(self.root,self.path,'',True)

    def test_repeat_setup_preserves_explicit_new_report_destinations(self):
        configure(self.root,self.path,str(self.node))
        path=self.service/'config.local.json'
        config=json.loads(path.read_text())
        config['new_report_destinations']={'new-sales':{'folder':'/Test','name':'New Sales'}}
        config['clients']['stair']['create_reports']=['new-sales']
        config['clients']['stair']['automatic_publication']={'reports':['new-sales','staging'],'actions':['publish','create']}
        path.write_text(json.dumps(config))
        configure(self.root,self.path,str(self.node))
        config=json.loads(path.read_text())
        self.assertEqual(config['new_report_destinations']['new-sales']['name'],'New Sales')
        self.assertIn('create',config['clients']['stair']['scopes'])
        self.assertIn('new-sales',config['clients']['stair']['reports'])
        self.assertEqual(config['clients']['stair']['automatic_publication']['reports'],['new-sales','staging'])


if __name__=='__main__':unittest.main()
