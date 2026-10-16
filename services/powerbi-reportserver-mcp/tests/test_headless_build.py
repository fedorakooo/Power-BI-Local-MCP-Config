import json
import tempfile
import unittest
from pathlib import Path

from pbirs_mcp.headless_build import ThinReportBuilder


class HeadlessScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        (self.source / 'Report').mkdir(parents=True)
        (self.source / 'Report/report.json').write_text('{"sections": []}')
        (self.source / 'Version.txt').write_text('1.28')
        self.connection = 'Data Source=localhost:23831;Initial Catalog=Lab;Cube=Model'
        self.write_connection(self.connection)
        self.builder = ThinReportBuilder({'release_root': str(self.root / 'release'),
            'headless_build_root': str(self.root / 'builds'), 'headless_projects': {'lab': {
                'source_root': str(self.source), 'report_version': '1.28', 'connection_string': self.connection}}})

    def write_connection(self, value, remote=False):
        payload = {'Connections': [{'ConnectionType': 'analysisServicesDatabaseLive', 'ConnectionString': value}]}
        if remote:
            payload['RemoteArtifacts'] = [{'DatasetId': 'unreviewed'}]
        (self.source / 'Connections.json').write_text(json.dumps(payload))

    def test_embedded_model_cannot_silently_become_thin_report(self):
        (self.source / 'Model').mkdir()
        with self.assertRaisesRegex(ValueError, 'Embedded models'):
            self.builder.inspect('lab')

    def test_unreviewed_connection_cannot_change_target(self):
        self.write_connection('Data Source=another-server;Initial Catalog=Other')
        with self.assertRaisesRegex(ValueError, 'operator-enrolled target'):
            self.builder.inspect('lab')

    def test_password_cannot_enter_release_package(self):
        self.write_connection(self.connection + ';Password=not-a-real-secret')
        with self.assertRaisesRegex(ValueError, 'Credentials must not'):
            self.builder.inspect('lab')

    def test_cloud_reference_cannot_override_ssas_connection(self):
        self.write_connection(self.connection, remote=True)
        with self.assertRaisesRegex(ValueError, 'Cloud artifact'):
            self.builder.inspect('lab')

    def test_unenrolled_project_is_refused(self):
        with self.assertRaises(PermissionError):
            self.builder.inspect('other-customer')


if __name__ == '__main__':
    unittest.main()
