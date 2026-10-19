import subprocess
import unittest
from unittest.mock import Mock, patch

from pbirs_mcp.desktop_save import DesktopBridge


class DesktopModelIdentityTests(unittest.TestCase):
    @patch('pbirs_mcp.desktop_save.subprocess.run')
    def test_discovery_binds_engine_name_and_verified_parent_pid(self, run):
        run.return_value = Mock(returncode=0, stdout='6176')
        self.assertEqual(DesktopBridge.model_engine_pids(5476), [6176])
        command = run.call_args.args[0][-1]
        self.assertIn("Name='msmdsrv.exe' AND ParentProcessId=5476", command)

    @patch('pbirs_mcp.desktop_save.subprocess.run')
    def test_failed_discovery_does_not_guess_an_engine(self, run):
        for result in (Mock(returncode=1, stdout='6176'), Mock(returncode=0, stdout=''),
                       Mock(returncode=0, stdout='{"ProcessId":6176}')):
            run.return_value = result
            self.assertEqual(DesktopBridge.model_engine_pids(5476), [])
        run.side_effect = subprocess.TimeoutExpired('powershell', 15)
        self.assertEqual(DesktopBridge.model_engine_pids(5476), [])

    def test_invalid_pid_is_rejected_before_execution(self):
        for pid in (0, -1, True, '5476; Stop-Process'):
            with self.assertRaises(ValueError):
                DesktopBridge.model_engine_pids(pid)


if __name__ == '__main__':
    unittest.main()
