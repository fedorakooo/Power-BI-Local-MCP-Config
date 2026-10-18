"""Build a source-only archive without credentials, runtime files or virtual environments."""
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = Path(sys.argv[1]).resolve()
files = [root / name for name in ('.gitignore', 'README.md', 'STAIR.md', 'LOCAL-CODEX.md', 'LOCAL-VALIDATION.md', 'NEW-WINDOWS.md', 'TEST-PROMPT.md', 'requirements.txt', 'requirements-lock.txt', 'server.py')]
for directory in ('pbirs_mcp', 'scripts', 'tests'):
    files.extend(p for p in (root / directory).iterdir() if p.suffix in ('.py', '.ps1'))
files.extend([root / 'modeling/package.json', root / 'modeling/pnpm-lock.yaml'])
files.extend([root / 'gateway/package.json', root / 'gateway/pnpm-lock.yaml', root / 'gateway/Caddyfile'])
files.extend([root / 'bridge/package.json', root / 'bridge/pnpm-lock.yaml'])
files.extend((root / 'schemas').glob('*.json'))
with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, 'powerbi-reportserver-mcp/' + path.relative_to(root).as_posix())
print('Source-only package: ' + str(destination))
