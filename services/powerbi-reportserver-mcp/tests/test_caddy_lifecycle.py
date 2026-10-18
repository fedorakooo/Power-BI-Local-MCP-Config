import ctypes
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'nt', 'Windows process lifecycle regression')
class CaddyLifecycleTests(unittest.TestCase):
    def alive(self, pid):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)

    def test_parent_pipe_eof_stops_actual_child_process(self):
        script_dir = Path(__file__).resolve().parents[1] / 'scripts'
        code = ('import sys; sys.path.insert(0, ' + repr(str(script_dir)) + '); '
                'from supervise_caddy import supervise; '
                'sys.exit(supervise([sys.executable,"-c","import time; time.sleep(90)"]))')
        # Use pythonw as in the real scheduled supervisor, with explicit stdio.
        executable = str(Path(sys.executable).with_name('pythonw.exe'))
        wrapper = subprocess.Popen([executable, '-u', '-c', code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child_pid = None
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                started = json.loads(pool.submit(wrapper.stdout.readline).result(timeout=10))
            child_pid = started['child_pid']
            self.assertTrue(self.alive(child_pid))
            wrapper.stdin.close()
            wrapper.wait(timeout=15)
            self.assertEqual(wrapper.returncode, 0)
            self.assertFalse(self.alive(child_pid), 'Orphaned proxy child survived the parent pipe closing')
        finally:
            if wrapper.poll() is None:
                wrapper.kill(); wrapper.wait(timeout=5)
            wrapper.stdout.close(); wrapper.stderr.close()
            if child_pid and self.alive(child_pid):
                subprocess.run(['taskkill', '/PID', str(child_pid), '/F'], capture_output=True, check=False)


if __name__ == '__main__':
    unittest.main()
