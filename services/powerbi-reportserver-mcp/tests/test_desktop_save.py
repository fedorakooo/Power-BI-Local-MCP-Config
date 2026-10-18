import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from pbirs_mcp.core import sha256
from pbirs_mcp.desktop_save import SaveService


def artifact(path, content):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('DataModel', content)
        archive.writestr('Report/Layout', '{}')


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'report.pbix'; artifact(self.file, 'before')
        self.before = sha256(self.file)
        self.calls = 0; self.busy_reads = 0; self.fail = False
        test = self
        class Backend:
            def ensure_unlocked(self): pass
            def invoke_save(self, main):
                test.calls += 1
                if test.fail: raise RuntimeError('Invoke failed')
                artifact(test.file, 'after')
                return 'uia_button'
        class Worker:
            backend = Backend()
            def main(self, project): return {'pid': 2, 'hwnd': 3}
        class Bridge:
            def state(self, pid):
                if test.calls and not test.busy_reads:
                    test.busy_reads += 1
                    raise RuntimeError('Temporarily busy')
                return {'currentFilePath': str(test.file), 'hasUnsavedChanges': not bool(test.calls)}
        self.bridge = Bridge()
        self.config = {'data_root': str(self.root / 'runtime'), 'release_root': str(self.root),
                       'desktop_save_targets': {'demo': str(self.file)}}
        self.service = SaveService(self.config, Worker(), self.bridge)

    def test_backup_and_transient_read_recovery_do_not_repeat_save(self):
        with patch('pbirs_mcp.desktop_save.time.sleep'):
            result = self.service.save('demo', self.before)
        self.assertEqual(result['status'], 'saved_verified')
        self.assertEqual(self.calls, 1)
        self.assertNotEqual(result['sha256'], self.before)
        self.assertEqual(sha256(self.service.root / (result['backup_id']+'.pbix')), self.before)
        self.assertEqual(self.busy_reads, 1)

    def test_clean_file_is_verified_without_invoking_disabled_save(self):
        self.bridge.state = lambda pid: {'currentFilePath': str(self.file), 'hasUnsavedChanges': False}
        result = self.service.save('demo', self.before)
        self.assertEqual(result['status'], 'saved_verified')
        self.assertEqual(result['save_invocation_method'], 'already_saved')
        self.assertEqual(result['save_invocations'], 0)
        self.assertEqual(result['sha256'], self.before)
        self.assertEqual(self.calls, 0)

    def test_stale_file_does_not_invoke_save(self):
        with self.assertRaises(ValueError): self.service.save('demo', '0'*64)
        self.assertEqual(self.calls, 0)

    def test_unenrolled_report_does_not_invoke_save(self):
        with self.assertRaises(PermissionError): self.service.save('other', self.before)
        self.assertEqual(self.calls, 0)

    def test_different_open_file_does_not_invoke_save(self):
        self.bridge.state = lambda pid: {'currentFilePath': str(self.root/'other.pbix'), 'hasUnsavedChanges': True}
        with self.assertRaises(PermissionError): self.service.save('demo', self.before)
        self.assertEqual(self.calls, 0)

    def test_uncertain_invocation_preserves_backup_and_does_not_retry(self):
        self.fail = True
        with self.assertRaisesRegex(RuntimeError, 'outcome uncertain'): self.service.save('demo', self.before)
        self.assertEqual(self.calls, 1)
        records = list(self.service.root.glob('*.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertEqual(record['status'], 'save_outcome_uncertain')
        self.assertEqual(sha256(self.service.root/(record['backup_id']+'.pbix')), self.before)
        self.assertFalse(list(self.service.root.glob('*.lock')))
