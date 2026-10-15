import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from pbirs_mcp.core import Service, sha256


def pbix(label):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('Report/Layout', label)
    return stream.getvalue()


class Backend:
    def __init__(self):
        self.content = pbix('old')
        self.uploads = 0
        self.fail_after_upload = False

    def call(self, operation, **kwargs):
        item = dict(Id='00000000-0000-0000-0000-000000000001', Name='Sales', Path='/Team/Sales')
        if operation == 'list':
            return {'reports': [item]}
        if operation == 'get':
            return {'report': item}
        if operation == 'download':
            if self.fail_after_upload and self.uploads:
                raise RuntimeError('network error')
            Path(kwargs['destination']).write_bytes(self.content)
            return {}
        if operation == 'upload':
            self.uploads += 1
            self.content = Path(kwargs['source']).read_bytes()
            return {}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = Backend()
        self.svc = Service(dict(portal='http://localhost/Reports', data_root=str(self.root / 'private'),
                           release_root=str(self.root / 'release'), write_enabled=True,
                           reports={'sales': '00000000-0000-0000-0000-000000000001'},
                           clients={'author': {'reports': ['sales'], 'scopes': ['read', 'backup', 'publish']},
                                    'reader': {'reports': ['sales'], 'scopes': ['read']}}), self.backend)
        self.file = self.svc.release / 'Sales.pbix'
        self.file.write_bytes(pbix('new'))

    def approval(self, *, action='publish', file=None, expected=None, actor='author'):
        backup = self.svc.download_report_backup('author', 'sales')
        data = dict(actor=actor, report='sales', action=action, sha256=sha256(file or self.file),
                    expected_current_sha256=expected or backup['sha256'], expires_at=time.time() + 100)
        approval_name = 'restore-approval' if action == 'restore' else 'approval'
        (self.svc.root / 'approvals' / (approval_name + '.json')).write_text(json.dumps(data))
        return backup

    def test_publish_backs_up_verifies_and_consumes_approval(self):
        self.approval()
        result = self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['url'], 'http://localhost/Reports/powerbi/Team/Sales')
        with self.assertRaises(PermissionError):
            self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')
        self.assertEqual(self.backend.uploads, 1)

    def test_scope_and_report_authorization(self):
        with self.assertRaises(PermissionError):
            self.svc.publish_reviewed_pbix('reader', 'sales', 'Sales.pbix', 'approval')
        with self.assertRaises(PermissionError):
            self.svc.get_report_link('author', 'other')

    def test_traversal_denied(self):
        for name in ('../Sales.pbix', '..\\Sales.pbix', '/Sales.pbix'):
            with self.assertRaises(ValueError):
                self.svc.publish_reviewed_pbix('author', 'sales', name, 'approval')

    def test_changed_file_denied(self):
        self.approval()
        self.file.write_bytes(pbix('tampered'))
        with self.assertRaises(PermissionError):
            self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')
        self.assertEqual(self.backend.uploads, 0)

    def test_changed_report_denied(self):
        self.approval(expected='0' * 64)
        with self.assertRaises(PermissionError):
            self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')
        self.assertEqual(self.backend.uploads, 0)

    def test_uncertain_upload_consumes_approval_and_preserves_backup(self):
        self.approval()
        self.backend.fail_after_upload = True
        with self.assertRaisesRegex(RuntimeError, 'Outcome may be uncertain'):
            self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')
        self.assertTrue((self.svc.root / 'consumed' / 'approval.json').exists())
        self.assertTrue(list((self.svc.root / 'backups').glob('*.pbix')))

    def test_restore_requires_approval_and_restores_content(self):
        backup = self.approval()
        old_bytes = self.backend.content
        self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')
        path = self.svc.root / 'backups' / (backup['backup_id'] + '.pbix')
        self.approval(action='restore', file=path)
        result = self.svc.restore_previous_pbix('author', 'sales', backup['backup_id'], 'restore-approval')
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(self.backend.content, old_bytes)

    def test_write_disabled(self):
        self.svc.config['write_enabled'] = False
        with self.assertRaises(PermissionError):
            self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')

    def test_approval_cannot_be_used_by_another_actor(self):
        self.approval(actor='other')
        with self.assertRaises(PermissionError):
            self.svc.publish_reviewed_pbix('author', 'sales', 'Sales.pbix', 'approval')


if __name__ == '__main__':
    unittest.main()
