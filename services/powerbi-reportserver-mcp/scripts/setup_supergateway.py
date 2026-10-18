"""Configure STAIR pilot Supergateway processes. Frontend auth is off by user request."""
import hashlib
import json
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config_path = root / 'config.local.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
runtime = Path(config['data_root'])
keys = {}
for name in ('modeling', 'reportserver'):
    path = runtime / ('stair-' + name + '.key')
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48) + '\n', encoding='utf-8')
    keys[name] = path

credential = config.get('credential_path')
if not credential or not Path(credential).is_file():
    raise SystemExit('Configure the Windows-protected Report Server credential first')
config['clients']['stair'] = {
    'token_sha256': hashlib.sha256(keys['reportserver'].read_text().strip().encode()).hexdigest(),
    'scopes': ['read', 'backup', 'publish'],
    'reports': config['clients']['local-operator']['reports'],
    'credential_path': credential,
}
config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
binaries = list((root / 'modeling/node_modules/.pnpm').rglob('powerbi-modeling-mcp.exe'))
if len(binaries) != 1:
    raise SystemExit('Expected one pinned Microsoft Modeling MCP binary')
# Supervisor manifest, not native Supergateway CLI configuration. Published 4.1.0
# starts one stdio child per process; Caddy routes the two HTTP endpoints.
gateway = dict(mcpServers={
    'stair-powerbi-modeling': dict(command=str(binaries[0]),
        args=['--start', '--readwrite', '--accepteula']),
    'stair-powerbi-reportserver': dict(command=str(root / '.venv/Scripts/python.exe'),
        args=[str(root / 'server.py'), '--config', str(config_path)], cwd=str(root),
        env={'PBIRS_STDIO_ACTOR': 'stair'}),
    'stair-powerbi-authoring': dict(command=str(root / '.venv/Scripts/python.exe'),
        args=['-m', 'pbirs_mcp.report_authoring', '--config', str(config_path)]),
    'stair-powerbi-desktop': dict(command=str(root / '.venv/Scripts/python.exe'),
        args=['-m', 'pbirs_mcp.windows_worker', '--config', str(config_path)]),
})
(root / 'gateway/servers.local.json').write_text(json.dumps(gateway, indent=2), encoding='utf-8')
print('Configured four stateful HTTP endpoints. Caddy frontend uses source-IP restrictions without API keys.')
