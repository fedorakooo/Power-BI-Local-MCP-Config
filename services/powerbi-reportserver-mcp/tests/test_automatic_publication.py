import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from pbirs_mcp.core import Service, sha256
from test_service import Backend, pbix


class AutomaticPublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.backend = Backend()
        self.config = dict(portal='http://localhost/Reports', data_root=str(root/'private'),
            release_root=str(root/'release'), write_enabled=True,
            reports={'sales':'00000000-0000-0000-0000-000000000001'}, clients={
                'author': {'scopes':['read','backup','publish'], 'reports':['sales'],
                    'automatic_publication': {'reports':['sales'],'actions':['publish']}},
                'manual': {'scopes':['read','backup','publish'], 'reports':['sales']}})
        self.service = Service(self.config, self.backend)
        self.file = self.service.release/'new.pbix'
        self.file.write_bytes(pbix('new'))
        self.old = hashlib.sha256(self.backend.content).hexdigest()

    def publish(self, **kwargs):
        return self.service.publish_reviewed_pbix('author','sales','new.pbix',
            expected_sha256=sha256(self.file),expected_current_sha256=self.old,**kwargs)

    def test_automatic_update_backs_up_uploads_and_verifies_without_an_approval(self):
        result = self.publish()
        self.assertEqual(result['status'],'verified')
        self.assertEqual(result['publication_mode'],'automatic')
        self.assertEqual(self.backend.uploads,1)
        backup=self.service.root/'backups'/(result['backup_id']+'.pbix')
        self.assertEqual(sha256(backup),self.old)
        journal=json.loads(next((self.service.root/'automatic-operations').glob('*.json')).read_text())
        self.assertEqual(journal['status'],'verified')

    def test_wrong_artifact_hash_and_changed_server_hash_prevent_upload(self):
        with self.assertRaises(PermissionError):
            self.service.publish_reviewed_pbix('author','sales','new.pbix',expected_sha256='0'*64,expected_current_sha256=self.old)
        self.backend.content=pbix('concurrent change')
        with self.assertRaisesRegex(PermissionError,'Report changed'):
            self.publish()
        self.assertEqual(self.backend.uploads,0)

    def test_missing_server_hash_or_manual_caller_still_cannot_upload(self):
        with self.assertRaises(PermissionError):
            self.service.publish_reviewed_pbix('author','sales','new.pbix',expected_sha256=sha256(self.file))
        with self.assertRaisesRegex(PermissionError,'operator approval'):
            self.service.publish_reviewed_pbix('manual','sales','new.pbix')
        self.assertEqual(self.backend.uploads,0)

    def test_uncertain_write_blocks_any_new_automatic_attempt_even_after_restart(self):
        self.backend.fail_after_upload=True
        with self.assertRaisesRegex(RuntimeError,'automatic retries blocked'):
            self.publish()
        self.backend.fail_after_upload=False
        self.file.write_bytes(pbix('another version'))
        self.old=hashlib.sha256(self.backend.content).hexdigest()
        self.service=Service(self.config,self.backend)
        with self.assertRaisesRegex(PermissionError,'unresolved operation'):
            self.publish()
        self.assertEqual(self.backend.uploads,1)

    def test_policy_is_actor_and_action_scoped(self):
        self.assertEqual(self.service.get_publication_policy('author','sales')['publish'],'automatic')
        self.assertEqual(self.service.get_publication_policy('manual','sales')['publish'],'operator_approval')
        self.assertEqual(self.service.get_publication_policy('author','sales')['restore'],'operator_approval')
        with self.assertRaises(PermissionError):
            self.service.get_publication_policy('author','another-customer')


if __name__=='__main__':unittest.main()
