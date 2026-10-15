import hashlib
import urllib.request
import zipfile
from pathlib import Path

VERSION = '2.11.7'
root = Path(__file__).resolve().parents[1]
directory = root / 'runtime/bin'
directory.mkdir(exist_ok=True)
name = f'caddy_{VERSION}_windows_amd64.zip'
base = f'https://github.com/caddyserver/caddy/releases/download/v{VERSION}/'
archive = directory / name
urllib.request.urlretrieve(base + name, archive)
checksums = urllib.request.urlopen(base + f'caddy_{VERSION}_checksums.txt').read().decode()
expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1].lstrip('*') == name)
actual = hashlib.sha512(archive.read_bytes()).hexdigest()
if expected.lower() != actual:
    raise SystemExit('Caddy archive checksum mismatch')
with zipfile.ZipFile(archive) as package:
    (directory / 'caddy.exe').write_bytes(package.read('caddy.exe'))
print('Installed Caddy ' + VERSION + '; official archive SHA512 verified')
