"""Generate an enrolled thin-report configuration; never replace existing sources."""
import argparse
import copy
import hashlib
import json
import os
import zipfile
from pathlib import Path


def configure(root, settings, server):
    root = Path(root).resolve()
    connection = settings.get('connection_string', '')
    if settings['mode'] == 'lab':
        connection = f'Data Source={server};Initial Catalog=PowerBIMcpHeadlessLab;Cube=Model'
        source = root / 'headless/projects/headless-lab'
        if not source.exists():
            # Generate only the synthetic test report from the reviewed repository seed.
            source.mkdir(parents=True)
            (source / 'Report').mkdir()
            with zipfile.ZipFile(root / 'reports/Fedaraka Server Automated.pbix') as archive:
                report = json.loads(archive.read('Report/Layout').decode('utf-16-le'))
                page = copy.deepcopy(next(p for p in report['sections'] if p['displayName'] == 'Page 1'))
                page.update(displayName='Headless SSAS validation', ordinal=0, filters='[]', config='{}')
                for visual in page['visualContainers']:
                    for key in ('config', 'query', 'dataTransforms'):
                        visual[key] = (visual[key].replace('#Measures', 'Sales')
                            .replace('Fedaraka MCP Win Rate %', 'Win Rate % v2')
                            .replace('dim_SaleTeams', 'Sales').replace('manager', 'Manager'))
                report['sections'] = [page]
                report_config = json.loads(report['config'])
                report_config.update(activeSectionIndex=0, bookmarks=[])
                report['config'] = json.dumps(report_config)
                (source / 'Report/report.json').write_text(json.dumps(report), encoding='utf-8')
                (source / 'Version.txt').write_text(archive.read('Version').decode('utf-16-le'), encoding='utf-8')
                for name in archive.namelist():
                    prefix = 'Report/StaticResources/'
                    if name.startswith(prefix) and not name.endswith('/'):
                        target = source / 'StaticResources' / name[len(prefix):]
                        if not target.resolve().is_relative_to(source.resolve()):
                            raise ValueError('Resource escapes project')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))
            metadata = {'Version': 5, 'AutoCreatedRelationships': [], 'FileDescription': '',
                        'CreatedFrom': 'Cloud', 'CreatedFromRelease': '2021.11'}
            report_settings = {'Version': 1, 'ReportSettings': {}, 'QueriesSettings': {
                'TypeDetectionEnabled': True, 'RelationshipImportEnabled': True,
                'RunBackgroundAnalysis': True, 'Version': '2.81.5831.821'}}
            for name, content in (('ReportMetadata.json', metadata), ('ReportSettings.json', report_settings),
                                  ('.pbixproj.json', {'version': '1.0'})):
                (source / name).write_text(json.dumps(content), encoding='utf-8')
            (source / '.mcp-lab-source').write_text('synthetic-test-only', encoding='ascii')
        if (source / '.mcp-lab-source').read_text() != 'synthetic-test-only':
            raise ValueError('Refusing to configure a source without the lab enrollment marker')
        # Refresh only the lab connection after a dynamic SSAS port changes.
        (source / 'Connections.json').write_text(json.dumps({'Version': 1, 'Connections': [{
            'Name': 'EntityDataSource', 'ConnectionString': connection,
            'ConnectionType': 'analysisServicesDatabaseLive'}]}), encoding='utf-8')
    else:
        source = Path(settings['source_root'])
        if not source.is_absolute():
            raise ValueError('Existing source_root must be absolute')
    compiler = root / 'tools/headless/compiler/pbi-tools.core.exe'
    config = {
        'release_root': str(root / 'services/powerbi-reportserver-mcp/runtime/release'),
        'headless_build_root': str(root / 'runtime/headless/builds'),
        'headless_compiler': str(compiler),
        'headless_compiler_sha256': hashlib.sha256(compiler.read_bytes()).hexdigest(),
        'headless_dotnet_root': str(root / 'tools/headless/dotnet'),
        'headless_projects': {settings['project']: {'source_root': str(source),
            'report_version': settings['report_version'], 'connection_string': connection}}}
    config['headless_creation_root'] = str(root / 'headless/created-reports')
    if settings['mode'] == 'lab':
        config['headless_creation_profiles'] = {settings['project']: {
            'description': 'Synthetic sales lab: Manager, Win Rate %, Win Rate % v2. Live SSAS; no embedded model.',
            'compatibility_source': str(source), 'report_version': settings['report_version'],
            'connection_string': connection, 'schema': {'Sales': {
                'columns': {'Manager': {'type': 'string'}},
                'measures': {'Win Rate %': {'format': '0.00%'}, 'Win Rate % v2': {'format': '0.00%'}}}}}}
    else:
        # Existing customer models need an explicitly supplied field schema.
        config['headless_creation_profiles'] = settings.get('creation_profiles', {})
    import sys
    sys.path.insert(0, str(root / 'services/powerbi-reportserver-mcp'))
    from pbirs_mcp.headless_build import ThinReportBuilder
    ThinReportBuilder(config).inspect(settings['project'])
    destination = root / 'headless/config.local.json'
    pending = destination.with_suffix('.tmp')
    pending.write_text(json.dumps(config, indent=2), encoding='utf-8')
    os.replace(pending, destination)
    print(json.dumps({'status': 'configured', 'config': str(destination), 'project': settings['project']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--server', default='')
    args = parser.parse_args()
    configure(args.root, json.loads(Path(args.settings).read_text(encoding='utf-8-sig')), args.server)
