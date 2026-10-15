"""Generate host-local configuration; never import credentials from the source bundle."""
import argparse
import hashlib
import ipaddress
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

NAMES = ('modeling', 'reportserver', 'authoring', 'desktop')


def configure(root, settings_path, node, validate_only=False):
    root = Path(root).resolve()
    settings = json.loads(Path(settings_path).read_text(encoding='utf-8-sig'))
    service = root / 'services/powerbi-reportserver-mcp'
    portal = urlsplit(settings['portal'])
    if portal.scheme not in ('http', 'https') or not portal.hostname or portal.username or portal.query or portal.fragment:
        raise ValueError('Invalid Report Server portal')
    port = settings['frontend_port']
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65530:
        raise ValueError('frontend_port must leave room for four backend ports')
    allowed = settings['allowed_addresses']
    if not isinstance(allowed, list) or not allowed:
        raise ValueError('allowed_addresses must be a nonempty list')
    for value in allowed:
        if not isinstance(value, str):
            raise ValueError('Network addresses must be strings')
        network = ipaddress.ip_network(value, strict=False)
        if network.prefixlen == 0:
            raise ValueError('Do not expose the no-key pilot to all addresses')
    for loopback in ('127.0.0.1', '::1'):
        if loopback not in allowed:
            allowed.append(loopback)
    uuid.UUID(settings['report_id'])
    if not isinstance(settings.get('enable_publication'), bool):
        raise ValueError('enable_publication must be true or false, not a string')
    for key in ('report_alias', 'project_alias'):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', settings[key]):
            raise ValueError('Invalid ' + key)
    source = (root / settings['report_file']).resolve()
    if not source.is_relative_to(root / 'reports') or source.suffix.lower() != '.pbix' or not source.is_file():
        raise ValueError('report_file must be an existing PBIX inside reports/')
    for name, dependency, version in (
        ('modeling', '@microsoft/powerbi-modeling-mcp', '1.0.0'),
        ('gateway', 'supergateway', '4.1.0'),
        ('bridge', '@microsoft/powerbi-desktop-bridge-cli', '1.0.0'),
    ):
        package = json.loads((service/name/'package.json').read_text())
        if package['dependencies'].get(dependency) != version:
            raise ValueError('Unexpected dependency pin: ' + dependency)
        if not (service/name/'pnpm-lock.yaml').is_file():
            raise ValueError('Missing dependency lockfile: ' + name)
    report_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() or 'Report/Layout' not in archive.namelist() or 'DataModel' not in archive.namelist():
            raise ValueError('Use the tested compatible PBIX with Report/Layout and DataModel')
    result = {'service_root': str(service), 'frontend_port': port,
              'backend_ports': list(range(port+1, port+5)), 'allowed_addresses': allowed,
              'report_sha256': report_hash, 'project_alias': settings['project_alias']}
    if validate_only:
        return dict(result, status='configuration_valid_no_changes')
    if not Path(node).is_file():
        raise ValueError('Node.js executable not found')
    runtime = service/'runtime'
    release = runtime/'release'
    release.mkdir(parents=True, exist_ok=True)
    working = release/source.name
    if not working.exists():
        shutil.copyfile(source, working)
    credential = runtime/'pbirs-credential.xml'
    actors = {name: {'scopes': ['read', 'backup', 'publish'], 'reports': [settings['report_alias']],
                     'credential_path': str(credential)} for name in ('local-operator', 'fedaraka')}
    config = {'portal': settings['portal'], 'data_root': str(runtime), 'release_root': str(release),
              'credential_path': str(credential), 'write_enabled': bool(settings['enable_publication']),
              'reports': {settings['report_alias']: settings['report_id']}, 'clients': actors,
              'desktop_executable': settings['desktop_executable'],
              'desktop_reports': {settings['project_alias']: str(working)},
              'desktop_save_targets': {settings['project_alias']: str(working)}, 'authoring_projects': {}}
    config_path = service/'config.local.json'
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    (runtime/'gateway-paths.json').write_text(json.dumps({'node': str(Path(node).resolve())}))
    binaries = list((service/'modeling/node_modules/.pnpm').rglob('powerbi-modeling-mcp.exe'))
    if len(binaries) != 1:
        raise ValueError('Expected one installed pinned Modeling MCP binary')
    python = str(service/'.venv/Scripts/python.exe')
    commands = [
        {'command': str(binaries[0]), 'args': ['--start', '--readwrite', '--accepteula']},
        {'command': python, 'args': [str(service/'server.py'), '--config', str(config_path)],
         'env': {'PBIRS_STDIO_ACTOR': 'fedaraka'}},
        {'command': python, 'args': ['-m', 'pbirs_mcp.report_authoring', '--config', str(config_path)]},
        {'command': python, 'args': ['-m', 'pbirs_mcp.windows_worker', '--config', str(config_path)]},
    ]
    manifest = {'mcpServers': {f'fedaraka-powerbi-{name}': dict(command, port=port+i+1)
                              for i, (name, command) in enumerate(zip(NAMES, commands))}}
    (service/'gateway/servers.local.json').write_text(json.dumps(manifest, indent=2))
    routes = []
    for i, name in enumerate(NAMES):
        routes.append(f'        handle_path /fedaraka-powerbi-{name}/* {{\n            reverse_proxy 127.0.0.1:{port+i+1} {{\n                flush_interval -1\n            }}\n        }}')
    caddy = '{\n    admin off\n    auto_https off\n    persist_config off\n}\n'
    caddy += f':{port} {{\n    @allowed remote_ip ' + ' '.join(allowed) + '\n    handle @allowed {\n'
    caddy += '\n'.join(routes) + '\n    }\n    respond "Forbidden" 403\n}\n'
    (service/'gateway/Caddyfile').write_text(caddy)
    generated = root/'generated'
    generated.mkdir(exist_ok=True)
    aliases = ('powerbi_modeling_local', 'powerbi_reportserver_local', 'powerbi_reportauthoring_local', 'powerbi_desktop_local')
    urls = {alias: f'http://127.0.0.1:{port}/fedaraka-powerbi-{name}/mcp' for alias, name in zip(aliases, NAMES)}
    toml = '\n'.join(f'[mcp_servers.{alias}]\nurl = "{url}"\nstartup_timeout_sec = 60\ntool_timeout_sec = 120\n' +
        ('enabled_tools = ["connection_operations", "database_operations", "model_operations", "table_operations", "column_operations", "relationship_operations", "measure_operations", "dax_query_operations", "transaction_operations"]\n' if alias == 'powerbi_modeling_local' else '')
        for alias, url in urls.items())
    (generated/'codex-mcp.toml').write_text(toml)
    (generated/'endpoints.json').write_text(json.dumps(urls, indent=2))
    return dict(result, status='host_configuration_generated_working_pbix_preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True); parser.add_argument('--config', required=True)
    parser.add_argument('--node', default=''); parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(configure(args.root, args.config, args.node, args.validate_only), indent=2))
