import json
import shutil
import tempfile
import unittest
from pathlib import Path
from configure_headless import configure


REPO = Path(__file__).resolve().parents[1]


class HeadlessSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'reports').mkdir()
        (self.root / 'headless').mkdir()
        compiler = self.root / 'tools/headless/compiler'
        compiler.mkdir(parents=True)
        (compiler / 'pbi-tools.core.exe').write_bytes(b'fixture-not-executable')
        shutil.copyfile(REPO / 'reports/STAIR Server Automated.pbix',
                        self.root / 'reports/STAIR Server Automated.pbix')
        self.settings = dict(mode='lab', project='headless-lab', report_version='1.28')

    def test_rerun_preserves_visual_edits_and_updates_lab_connection(self):
        configure(self.root, self.settings, 'localhost:12345')
        report = self.root / 'headless/projects/headless-lab/Report/report.json'
        layout = json.loads(report.read_text())
        layout['sections'][0]['displayName'] = 'Operator changed this page'
        report.write_text(json.dumps(layout))
        before = report.read_bytes()
        configure(self.root, self.settings, 'localhost:12346')
        self.assertEqual(before, report.read_bytes())
        connection = json.loads((report.parents[1] / 'Connections.json').read_text())
        self.assertIn('localhost:12346', connection['Connections'][0]['ConnectionString'])

    def test_existing_mode_never_rewrites_report_or_connection(self):
        configure(self.root, self.settings, 'localhost:12345')
        source = self.root / 'headless/projects/headless-lab'
        before = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
        settings = dict(mode='existing', project='customer', report_version='1.28',
                        source_root=str(source), connection_string='Data Source=localhost:12345;Initial Catalog=PowerBIMcpHeadlessLab;Cube=Model')
        configure(self.root, settings, '')
        self.assertEqual(before, {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()})

    def test_unmarked_project_is_not_adopted(self):
        source = self.root / 'headless/projects/headless-lab'
        source.mkdir(parents=True)
        (source / '.mcp-lab-source').write_text('customer-project')
        with self.assertRaisesRegex(ValueError, 'enrollment marker'):
            configure(self.root, self.settings, 'localhost:12345')


if __name__ == '__main__':
    unittest.main()
