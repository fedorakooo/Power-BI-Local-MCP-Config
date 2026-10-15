import json
import tempfile
import time
import unittest
from pathlib import Path
from pbirs_mcp.report_authoring import Authoring, MeasureCard
from pbirs_mcp.windows_worker import Worker, safe_file_name


class FakeDesktop:
    def __init__(self): self.inputs = []
    def windows(self): return [{'hwnd': 1, 'pid': 2, 'title': 'Demo'}]
    def capture(self, main):
        return dict(hwnd=1, main_hwnd=1, pid=2, title='Demo', rectangle=[0,0,100,100], width=100, height=100), b'png-test'
    def verify_target(self, state): pass
    def click(self, state, x, y): self.inputs.append(('click',x,y))
    def key(self, state, key): self.inputs.append(('key',key))
    def type_text(self, state, text): self.inputs.append(('text',text))


class WorkerGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = FakeDesktop()
        self.worker = Worker({'data_root': self.temp.name, 'authoring_projects': {
            'demo': str(Path(self.temp.name) / 'Demo.pbip')}}, self.backend)
    def token(self): return json.loads(self.worker.observe('demo')[0].text)['snapshot_id']
    def test_snapshot_consumed_and_cannot_replay(self):
        token = self.token()
        self.worker.act(token,'click',x=20,y=30)
        with self.assertRaises(ValueError): self.worker.act(token,'click',x=20,y=30)
        self.assertEqual(self.backend.inputs,[('click',20,30)])
    def test_expired_snapshot_has_no_input(self):
        token = self.token(); self.worker.snapshot['created'] -= 121
        with self.assertRaises(ValueError): self.worker.act(token,'key',key='enter')
        self.assertEqual(self.backend.inputs,[])
    def test_outside_window_rejected(self):
        with self.assertRaises(ValueError): self.worker.act(self.token(),'click',x=100,y=0)
        self.assertEqual(self.backend.inputs,[])
    def test_shell_shortcuts_and_paths_rejected(self):
        with self.assertRaises(ValueError): self.worker.act(self.token(),'key',key='win+r')
        with self.assertRaises(ValueError): self.worker.act(self.token(),'text',text='C:\\Windows\\x')
        self.assertEqual(self.backend.inputs,[])
    def test_unenrolled_report_rejected(self):
        with self.assertRaises(PermissionError): self.worker.observe('other')
    def test_release_filename_cannot_escape_or_use_devices(self):
        for name in ['../x.pbix','C:\\x.pbix','CON.pbix','x.exe']:
            with self.assertRaises(ValueError): safe_file_name(name)
        self.assertEqual(safe_file_name('Reviewed Report.pbix'),'Reviewed Report.pbix')


class ReportAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.report = root / 'Demo.Report'
        self.model = root / 'Demo.SemanticModel'
        (self.report / 'definition/pages').mkdir(parents=True)
        (self.model / 'definition/tables').mkdir(parents=True)
        (root / 'Demo.pbip').write_text(json.dumps({'artifacts':[{'report':{'path':'Demo.Report'}}]}))
        (self.report / 'definition.pbir').write_text(json.dumps({'datasetReference':{'byPath':{'path':'../Demo.SemanticModel'}}}))
        (self.report / 'definition/pages/pages.json').write_text(json.dumps({
            '$schema':'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json',
            'pageOrder':[]}))
        (self.model / 'definition/tables/Metrics.tmdl').write_text("table Metrics\n\tmeasure Won = 2\n\tmeasure Total = 5\n\tcolumn Manager\n")
        self.service = Authoring({'data_root':str(root / 'runtime'), 'authoring_projects':{'demo':str(root / 'Demo.pbip')}})
    def dashboard(self, revision, measure='Won'):
        return self.service.add_dashboard('demo',revision,'Demo KPI',
            [MeasureCard(table='Metrics',measure=measure,title='Won')],'Metrics','Manager')
    def test_schema_validated_page_and_backup_created(self):
        revision = self.service.revision('demo')
        result = self.dashboard(revision)
        self.assertEqual(result['visual_count'],2)
        self.assertNotEqual(revision,result['revision'])
        self.assertTrue((self.service.root / (result['backup_id']+'.zip')).exists())
        self.assertEqual(len(self.service.inspect('demo')['pages']),1)
    def test_stale_revision_rejected_without_changes(self):
        revision = self.service.revision('demo')
        with self.assertRaises(ValueError): self.dashboard('0'*64)
        self.assertEqual(revision,self.service.revision('demo'))
    def test_missing_binding_rejected_without_changes(self):
        revision = self.service.revision('demo')
        with self.assertRaises(ValueError): self.dashboard(revision,'Missing')
        self.assertEqual(revision,self.service.revision('demo'))
    def test_duplicate_page_rejected(self):
        result = self.dashboard(self.service.revision('demo'))
        with self.assertRaises(ValueError): self.dashboard(result['revision'])
        self.assertEqual(result['revision'],self.service.revision('demo'))
    def test_ratio_persisted_and_referenced_measures_checked(self):
        revision = self.service.revision('demo')
        result = self.service.add_ratio_measure('demo',revision,'Metrics','Win Rate','Won','Total')
        self.assertTrue(self.service.field_exists(self.model,'Metrics','Win Rate','measure'))
        with self.assertRaises(ValueError): self.service.add_ratio_measure('demo',result['revision'],'Metrics','Win Rate','Won','Total')


if __name__ == '__main__': unittest.main()
