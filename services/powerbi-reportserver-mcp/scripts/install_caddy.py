import hashlib
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

VERSION = '2.11.7'
ROOT = Path(__file__).resolve().parents[1]


def download(url, destination):
    import certifi
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    if os.environ.get('POWERBI_MCP_CA_BUNDLE'):
        context.load_verify_locations(cafile=os.environ['POWERBI_MCP_CA_BUNDLE'])
    try:
        with urllib.request.urlopen(url, context=context, timeout=120) as response:
            with Path(destination).open('wb') as output:
                shutil.copyfileobj(response, output)
    except urllib.error.URLError as error:
        if sys.platform != 'win32' or not isinstance(error.reason, ssl.SSLCertVerificationError):
            raise
        print('Python TLS trust check failed; retrying with Windows certificate validation.', flush=True)
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
            '-ExecutionPolicy', 'Bypass', '-File', str(ROOT/'scripts/Download-VerifiedHttps.ps1'),
            '-Url', url, '-Destination', str(destination)],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=150)
        if result.returncode:
            raise RuntimeError('Windows HTTPS download failed. Check proxy and trusted corporate CA, '
                'or set POWERBI_MCP_CA_BUNDLE to an approved PEM bundle. TLS verification remains enabled.') from None


def install(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = f'caddy_{VERSION}_windows_amd64.zip'
    base = f'https://github.com/caddyserver/caddy/releases/download/v{VERSION}/'
    with tempfile.TemporaryDirectory(prefix='caddy-download-', dir=directory) as temporary:
        archive = Path(temporary)/name
        checksums = Path(temporary)/'checksums.txt'
        print(f'Downloading Caddy {VERSION}...', flush=True)
        download(base + name, archive)
        print('Downloading official SHA512 checksums...', flush=True)
        download(base + f'caddy_{VERSION}_checksums.txt', checksums)
        rows = [line.split() for line in checksums.read_text(encoding='utf-8').splitlines()]
        matches = [row[0] for row in rows if len(row) == 2 and row[1].lstrip('*') == name]
        if len(matches) != 1 or matches[0].lower() != hashlib.sha512(archive.read_bytes()).hexdigest():
            raise RuntimeError('Caddy SHA512 check failed; installed binary was not changed')
        executable = Path(temporary)/'caddy.exe'
        with zipfile.ZipFile(archive) as package:
            executable.write_bytes(package.read('caddy.exe'))
        executable.replace(directory/'caddy.exe')
    print(f'Installed Caddy {VERSION}; official archive SHA512 verified', flush=True)


if __name__ == '__main__':
    install(ROOT/'runtime/bin')
