import hashlib
import importlib.util
import io
import ssl
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1]/'scripts/install_caddy.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_hash_failure_preserves_binary_and_verified_download_installs(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('caddy.exe', b'new-binary')
        data = buffer.getvalue()
        for valid in (False, True):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary)
                (destination/'caddy.exe').write_bytes(b'previous-binary')
                def download(url, path):
                    checksum = hashlib.sha512(data).hexdigest() if valid else '0'*128
                    Path(path).write_bytes(data if url.endswith('.zip') else f'{checksum}  caddy_{installer.VERSION}_windows_amd64.zip\n'.encode())
                with patch.object(installer, 'download', side_effect=download):
                    if valid:
                        installer.install(destination)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'SHA512'):
                            installer.install(destination)
                self.assertEqual((destination/'caddy.exe').read_bytes(), b'new-binary' if valid else b'previous-binary')
                self.assertEqual([p.name for p in destination.iterdir()], ['caddy.exe'])

    def test_certificate_failure_uses_windows_validation(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError('test trust failure'))
        with patch.object(installer.sys, 'platform', 'win32'), patch.object(installer.urllib.request, 'urlopen', side_effect=error), patch.object(installer.subprocess, 'run') as run:
            run.return_value.returncode = 0
            installer.download('https://example.com/archive.zip', 'test.zip')
            self.assertIn('Download-VerifiedHttps.ps1', str(run.call_args.args[0]))
            run.return_value.returncode = 1
            with self.assertRaisesRegex(RuntimeError, 'trusted corporate CA'):
                installer.download('https://example.com/archive.zip', 'test.zip')


if __name__ == '__main__':
    unittest.main()
