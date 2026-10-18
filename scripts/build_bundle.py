"""Build a transferable archive from an explicit source-file allowlist."""
import hashlib
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
service = root / 'services/powerbi-reportserver-mcp'
destination = Path(sys.argv[1]).resolve()
if destination.is_relative_to(root):
    raise SystemExit('Write the distributable outside the installation folder')
files = [root / name for name in (
    'Start-PowerBI.ps1', 'deployment.example.json', '.gitignore', 'README.ru.md', 'VALIDATION.md',
    'scripts/configure_deployment.py', 'scripts/check_runtime.py', 'scripts/test_deployment.py',
    'scripts/build_bundle.py', 'scripts/Select-Python.ps1', 'scripts/Test-PythonSelection.ps1', 'scripts/probe_python.py', 'scripts/Diagnose-Startup.ps1', 'scripts/Test-ReportServer.ps1', 'scripts/Test-Desktop.ps1', 'scripts/Stop-PortListeners.ps1', 'scripts/Write-StairEndpoints.ps1',
    'README.md', '.gitattributes', 'LICENSE', 'reports/Fedaraka Server Automated.pbix',
    'headless/README.md', 'headless/VALIDATION.md', 'headless/config.example.json',
    'scripts/Install-TestSSAS.ps1', 'scripts/Test-HeadlessSSAS.ps1', 'scripts/Diagnose-ReportServerSSAS.ps1', 'scripts/Grant-HeadlessLabReader.ps1',
    'Start-Headless.ps1', 'headless.deployment.example.json', 'headless/SETUP.ru.md',
    'scripts/configure_headless.py', 'scripts/check_headless.py', 'scripts/test_headless_setup.py',
    'scripts/start_headless_process.py', 'scripts/Select-HeadlessPowerShell.ps1',
    'scripts/Test-HeadlessPowerShellSelection.ps1', 'scripts/configure_headless_proxy.py',
    'scripts/test_headless_proxy.py')]
if not (root / 'reports/Fedaraka Server Automated.pbix').is_file():
    raise SystemExit('Supply your reviewed PBIX in reports/ before building a private deployment ZIP')
files += [service / name for name in (
    '.gitignore', 'README.md', 'FEDARAKA.md', 'LOCAL-CODEX.md', 'LOCAL-VALIDATION.md',
    'NEW-WINDOWS.md', 'TEST-PROMPT.md', 'requirements.txt', 'requirements-lock.txt', 'server.py',
    'modeling/package.json', 'modeling/pnpm-lock.yaml', 'gateway/package.json',
    'gateway/pnpm-lock.yaml', 'bridge/package.json', 'bridge/pnpm-lock.yaml')]
for directory in ('pbirs_mcp', 'scripts', 'tests'):
    files += [p for p in (service / directory).iterdir() if p.is_file() and p.suffix in ('.py', '.ps1')]
files += list((service / 'schemas').glob('*.json'))
destination.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(files)):
        archive.write(path, 'powerbi-mcp-deployment/' + path.relative_to(root).as_posix())
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    forbidden = {'runtime', 'generated', '.venv', 'node_modules', '__pycache__'}
    assert all(not forbidden.intersection(Path(name).parts) for name in names)
    assert all(Path(name).name not in ('deployment.local.json', 'config.local.json', 'servers.local.json') for name in names)
    assert sum(name.endswith('.pbix') for name in names) == 1
print(f'{destination}\nfiles={len(names)}\nsha256={hashlib.sha256(destination.read_bytes()).hexdigest()}')
