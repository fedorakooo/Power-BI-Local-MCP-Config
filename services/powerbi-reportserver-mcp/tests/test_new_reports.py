import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from pbirs_mcp.core import Service, sha256


class Catalog:
    def __init__(self):
        self.items = []
        self.creates = 0
        self.content = b''
        self.fail_download = False

    def call(self, operation, **kwargs):
        if operation == 'list':
            return {'reports': self.items}
        if operation == 'create':
            self.creates += 1
            self.content = Path(kwargs['source']).read_bytes()
            item = dict(Id='00000000-0000-0000-0000-000000000002', Name=kwargs['name'], Path=kwargs['folder']+'/'+kwargs['name'])
            self.items.append(item)
            return {'report': item}
        if operation == 'get':
            return {'report': self.items[0]}
        if operation == 'download':
            if self.fail_download:
                raise RuntimeError('Uncertain network failure')
            Path(kwargs['destination']).write_bytes(self.content)
            return {}
        raise AssertionError('Unexpected operation: ' + operation)


class NewReportPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.backend = Catalog()
        self.service = Service({'portal': 'http://localhost/Reports', 'data_root': str(root/'private'),
            'release_root': str(root/'release'), 'reports': {}, 'write_enabled': True,
            'new_report_destinations': {'new-sales': {'folder': '/MCP Test', 'name': 'Dynamic Sales'}},
            'clients': {'author': {'reports': ['new-sales'], 'create_reports': ['new-sales'],
                                  'scopes': ['read','backup','publish','create']}}}, self.backend)
        self.artifact = self.service.release / 'new.pbix'
        with zipfile.ZipFile(self.artifact, 'w') as z:
            z.writestr('Report/Layout', '{}')
        self.approval = self.service.root/'approvals/reviewed.json'
        self.approval.write_text(json.dumps({'actor':'author','report':'new-sales','action':'create',
            'sha256':sha256(self.artifact),'target_path':'/MCP Test/Dynamic Sales','expires_at':time.time()+100}))

    def publish(self):
        return self.service.publish_new_reviewed_pbix('author','new-sales','new.pbix','reviewed')

    def test_creation_verifies_hash_and_enrolls_link_persistently(self):
        result = self.publish()
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['url'], 'http://localhost/Reports/powerbi/MCP%20Test/Dynamic%20Sales')
        restarted = Service(self.service.config, self.backend)
        self.assertEqual(restarted.list_reports('author')[0]['alias'], 'new-sales')
        self.assertFalse(self.approval.exists())

    def test_existing_destination_is_never_overwritten(self):
        self.backend.items.append(dict(Id='existing',Name='dynamic sales',Path='/mcp test/dynamic sales'))
        with self.assertRaisesRegex(PermissionError, 'never overwrites'):
            self.publish()
        self.assertEqual(self.backend.creates,0)
        self.assertTrue(self.approval.exists())

    def test_missing_and_wrong_destination_approvals_cannot_publish(self):
        data = json.loads(self.approval.read_text())
        data['target_path']='/Another Customer/Report'
        self.approval.write_text(json.dumps(data))
        with self.assertRaises(PermissionError):
            self.publish()
        self.approval.unlink()
        with self.assertRaises(PermissionError):
            self.publish()
        self.assertEqual(self.backend.creates,0)

    def test_uncertain_creation_consumes_approval_and_does_not_retry(self):
        self.backend.fail_download=True
        with self.assertRaisesRegex(RuntimeError,'uncertain; approval consumed'):
            self.publish()
        self.assertFalse(self.approval.exists())
        with self.assertRaises(PermissionError):
            self.publish()
        self.assertEqual(self.backend.creates,1)

    def test_unenrolled_caller_cannot_create(self):
        self.service.config['clients']['author']['create_reports']=[]
        with self.assertRaises(PermissionError):
            self.publish()
        self.assertEqual(self.backend.creates,0)


if __name__=='__main__':
    unittest.main()
