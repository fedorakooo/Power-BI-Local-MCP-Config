import json
import tempfile
import unittest
from pathlib import Path
from pbirs_mcp.dynamic_reports import DynamicReports, ReportPage
from pbirs_mcp.headless_build import ThinReportBuilder


class CreationScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        base = root / 'base'
        (base / 'Report').mkdir(parents=True)
        (base / 'Report/report.json').write_text(json.dumps({'config': '{}',
            'sections': [{'displayName': 'OLD CUSTOMER PAGE', 'visualContainers': [{'secret': 'old-visual'}]}]}))
        for file, value in [('Version.txt', '1.28'), ('ReportMetadata.json', '{}'),
                            ('ReportSettings.json', '{}'), ('.pbixproj.json', '{"version":"1.0"}')]:
            (base / file).write_text(value)
        connection = 'Data Source=localhost:23831;Initial Catalog=Lab;Cube=Model'
        self.config = {'release_root': str(root / 'release'), 'headless_build_root': str(root / 'builds'),
            'headless_projects': {'protected': {'source_root': str(base)}}, 'headless_creation_root': str(root / 'created'),
            'headless_creation_profiles': {'lab': {'compatibility_source': str(base), 'report_version': '1.28',
                'connection_string': connection, 'schema': {'Sales': {'columns': {'Manager': {'type': 'string'}},
                    'measures': {'Win Rate %': {'format': '0.00%'}}}}}}}
        self.creator = DynamicReports(self.config)
        self.builder = ThinReportBuilder(self.config)
        self.pages = [ReportPage.model_validate({'title': 'New dashboard', 'visuals': [
            {'type': 'card', 'title': 'Rate', 'measure': {'table': 'Sales', 'name': 'Win Rate %'},
             'x': 20, 'y': 20, 'width': 300, 'height': 200} ]})]

    def test_new_report_has_new_visuals_and_an_enrolled_live_connection(self):
        self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        source = self.builder.project('sales-new')
        report = (source / 'Report/report.json').read_text()
        self.assertNotIn('OLD CUSTOMER PAGE', report)
        self.assertNotIn('old-visual', report)
        self.assertEqual(self.builder.inspect('sales-new')['pages'], ['New dashboard'])

    def test_duplicate_creation_does_not_overwrite_a_project(self):
        self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        before = self.builder.inspect('sales-new')['revision']
        with self.assertRaises(FileExistsError):
            self.creator.create('sales-new', 'lab', 'Replacement', self.pages)
        self.assertEqual(before, self.builder.inspect('sales-new')['revision'])

    def test_inspection_round_trips_all_supported_specs_and_escaped_titles(self):
        self.pages[0].visuals[0].title = "Owner's Rate"
        for kind, y in [('slicer', 250), ('columnChart', 400)]:
            spec = {'type': kind, 'title': kind, 'category': {'table': 'Sales', 'name': 'Manager'},
                    'x': 20, 'y': y, 'width': 300, 'height': 100}
            if kind == 'columnChart':
                spec['measure'] = {'table': 'Sales', 'name': 'Win Rate %'}
            self.pages[0].visuals.append(type(self.pages[0].visuals[0]).model_validate(spec))
        self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        self.assertEqual(self.builder.inspect('sales-new')['editable_pages'],
                         [page.model_dump(exclude_none=True) for page in self.pages])

    def test_add_page_from_inspection_preserves_first_page_visual_layout(self):
        self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        source = self.builder.project('sales-new') / 'Report/report.json'
        before = json.loads(source.read_text())['sections'][0]
        inspected = self.builder.inspect('sales-new')
        pages = [ReportPage.model_validate(p) for p in inspected['editable_pages']]
        extra = pages[0].model_copy(deep=True)
        extra.title = 'Second page'
        self.creator.update('sales-new', inspected['revision'], pages + [extra])
        after = json.loads(source.read_text())['sections'][0]
        self.assertEqual(before['displayName'], after['displayName'])
        for old, new in zip(before['visualContainers'], after['visualContainers']):
            self.assertEqual({k: old[k] for k in ('x', 'y', 'width', 'height')},
                             {k: new[k] for k in ('x', 'y', 'width', 'height')})
            self.assertEqual(json.loads(old['config'])['singleVisual'], json.loads(new['config'])['singleVisual'])

    def test_undeclared_fields_are_rejected_before_writing(self):
        self.pages[0].visuals[0].measure.name = 'OtherCustomerSecret'
        with self.assertRaisesRegex(ValueError, 'operator-enrolled'):
            self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        self.assertFalse((Path(self.config['headless_creation_root']) / 'sales-new').exists())

    def test_credentials_in_a_profile_cannot_be_written_to_new_sources(self):
        self.config['headless_creation_profiles']['lab']['connection_string'] += ';Password=not-a-real-secret'
        with self.assertRaisesRegex(ValueError, 'credential-free'):
            self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        self.assertFalse((Path(self.config['headless_creation_root']) / 'sales-new').exists())

    def test_stale_updates_are_rejected_and_valid_updates_back_up_layout(self):
        self.creator.create('sales-new', 'lab', 'Sales', self.pages)
        before = self.builder.inspect('sales-new')['revision']
        self.pages[0].title = 'Changed title'
        with self.assertRaisesRegex(ValueError, 'Project changed'):
            self.creator.update('sales-new', '0' * 64, self.pages)
        result = self.creator.update('sales-new', before, self.pages)
        backup = Path(self.config['headless_creation_root']) / '.backups' / (result['backup_id'] + '.json')
        self.assertEqual(json.loads(backup.read_text())['sections'][0]['displayName'], 'New dashboard')
        self.assertNotEqual(before, result['revision'])

    def test_operator_project_and_path_traversal_cannot_be_replaced(self):
        for project in ('protected', '../other'):
            with self.assertRaises(PermissionError):
                self.creator.create(project, 'lab', 'Sales', self.pages)

    def test_symlink_cannot_redirect_creation(self):
        root = Path(self.config['headless_creation_root'])
        root.mkdir()
        outside = root.parent / 'outside'
        outside.mkdir()
        try:
            (root / 'sales-new').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink permission unavailable')
        with self.assertRaises(ValueError):
            self.creator.create('sales-new', 'lab', 'Sales', self.pages)


if __name__ == '__main__':
    unittest.main()
