"""Experimental scoped MCP for compiling enrolled thin reports without Desktop."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from .dynamic_reports import DynamicReports, ReportPage

from mcp.server.fastmcp import FastMCP


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def revision(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Project links/reparse points are not permitted')
        if path.is_file():
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError('Project file exceeds the build limit')
            name = path.relative_to(root).as_posix().encode()
            result.update(len(name).to_bytes(4, 'big') + name)
            result.update(bytes.fromhex(digest(path)))
    return result.hexdigest()


class ThinReportBuilder:
    def __init__(self, config):
        self.config = config
        self.release = Path(config['release_root']).resolve()
        self.build_root = Path(config['headless_build_root']).resolve()

    def project(self, alias):
        settings = self.config.get('headless_projects', {}).get(alias)
        if not settings and self.config.get('headless_creation_root'):
            settings = DynamicReports(self.config).entry(alias)
        if not settings or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', alias):
            raise PermissionError('Headless project is not enrolled')
        raw_root = Path(settings['source_root'])
        if not raw_root.is_absolute() or raw_root.is_symlink() or getattr(raw_root.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Use a real absolute source directory')
        root = raw_root.resolve()
        if (root / 'Model').exists() or any(root.rglob('*.bim')) or any(root.rglob('*.tmdl')):
            raise ValueError('Embedded models cannot be compiled to PBIX by this backend; use SSAS and a thin report')
        if not (root / 'Report' / 'report.json').is_file():
            raise ValueError('An enrolled legacy PbixProj Report/report.json is required')
        version = (root / 'Version.txt').read_text(encoding='utf-8-sig').strip()
        if version != settings['report_version']:
            raise ValueError('Report version does not match the enrolled compatibility profile')
        connection = json.loads((root / 'Connections.json').read_text(encoding='utf-8-sig'))
        if connection.get('RemoteArtifacts'):
            raise ValueError('Cloud artifact references are not permitted in the SSAS profile')
        entries = connection.get('Connections', [])
        if len(entries) != 1 or entries[0].get('ConnectionType') != 'analysisServicesDatabaseLive':
            raise ValueError('Exactly one SSAS live connection is required')
        connection_string = entries[0].get('ConnectionString', '')
        if re.search(r'(?i)(?:^|;)\s*(password|pwd|user id|uid)\s*=', connection_string):
            raise ValueError('Credentials must not be embedded in report sources')
        if connection_string != settings['connection_string']:
            raise ValueError('SSAS connection differs from the operator-enrolled target')
        return root

    def inspect(self, alias):
        root = self.project(alias)
        layout = json.loads((root / 'Report/report.json').read_text(encoding='utf-8-sig'))
        return {'project': alias, 'revision': revision(root), 'backend': 'pbi-tools-thin-pbix',
            'pages': [p['displayName'] for p in layout.get('sections', [])],
            'page_details': [{'title': p['displayName'], 'visuals': [
                {'type': (c := json.loads(v.get('config', '{}'))).get('singleVisual', {}).get('visualType'),
                 'title': c.get('singleVisual', {}).get('vcObjects', {}).get('title', []),
                 'bindings': c.get('singleVisual', {}).get('projections', {})}
                for v in p.get('visualContainers', [])]} for p in layout.get('sections', [])],
            'gui_save_required': False, 'ssas_connection_verified': False,
            'reportserver_compatibility_verified': False, 'experimental': True}

    def build(self, alias, expected_revision):
        root = self.project(alias)
        if revision(root) != expected_revision:
            raise ValueError('Project changed since review; no build started')
        compiler = Path(self.config['headless_compiler']).resolve()
        if digest(compiler) != self.config['headless_compiler_sha256']:
            raise ValueError('Compiler SHA256 does not match the operator-pinned binary')
        self.build_root.mkdir(parents=True, exist_ok=True)
        self.release.mkdir(parents=True, exist_ok=True)
        build_id = uuid.uuid4().hex
        work = self.build_root / build_id
        work.mkdir()
        snapshot = work / 'source'
        shutil.copytree(root, snapshot)
        if revision(snapshot) != expected_revision:
            raise ValueError('Project changed during snapshot; no compiler invoked')
        artifact = work / 'report.pbix'
        env = os.environ.copy()
        if self.config.get('headless_dotnet_root'):
            env['DOTNET_ROOT'] = str(Path(self.config['headless_dotnet_root']).resolve())
        result = subprocess.run([str(compiler), 'compile', str(snapshot), '-outPath', str(artifact), '-format', 'PBIX'],
            cwd=work, env=env, capture_output=True, text=True, encoding='utf-8', timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (work / 'compiler.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode or not artifact.is_file():
            raise RuntimeError('Thin report compilation failed; inspect the local build log. Build ID: ' + build_id)
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() or 'DataModel' in archive.namelist() or 'Report/Layout' not in archive.namelist():
                raise ValueError('Compiler output is not a valid report-only PBIX')
            actual = json.loads(archive.read('Report/Layout').decode('utf-16-le'))
            expected = json.loads((snapshot / 'Report/report.json').read_text(encoding='utf-8-sig'))
            actual_connection = json.loads(archive.read('Connections').decode('utf-8-sig'))
            expected_connection = json.loads((snapshot / 'Connections.json').read_text(encoding='utf-8-sig'))
            if actual != expected or actual_connection != expected_connection:
                raise ValueError('Compiled report or connection does not match reviewed source')
        file_name = alias[:40] + '-' + build_id + '.pbix'
        destination = self.release / file_name
        # Unique destination; do not replace an existing release.
        pending = self.release / (file_name + '.partial')
        with pending.open('xb') as output, artifact.open('rb') as source:
            shutil.copyfileobj(source, output)
        if digest(pending) != digest(artifact):
            raise RuntimeError('Release copy verification failed')
        # Windows rename refuses an existing destination and exposes only a
        # complete verified artifact to the publication tool.
        if destination.exists():
            raise RuntimeError('Release already exists; refusing to replace it')
        pending.rename(destination)
        outcome = {'status': 'thin_pbix_built_verified', 'project': alias, 'build_id': build_id,
            'source_revision': expected_revision, 'file_name': file_name, 'sha256': digest(destination),
            'bytes': destination.stat().st_size, 'gui_save_used': False, 'published': False,
            'render_verified': False, 'experimental': True}
        (work / 'build.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
        return outcome


def build_mcp(config, **settings):
    service = ThinReportBuilder(config)
    creator = DynamicReports(config)
    mcp = FastMCP('Power BI Headless Thin Report Build (experimental)', **settings)

    @mcp.tool(annotations={'readOnlyHint': True})
    def list_report_workspace() -> dict:
        """List operator-enrolled SSAS models/fields and existing managed report projects. Models are live SSAS, not embedded import datasets."""
        reports = list(config.get('headless_projects', {}))
        if creator.root and creator.root.exists():
            reports += [p.name for p in creator.root.iterdir() if p.is_dir() and (p / '.mcp-created-report.json').is_file()]
        return {'models': creator.models(), 'projects': sorted(set(reports)),
                'supported_visuals': ['card', 'columnChart', 'slicer'], 'canvas': {'width': 1280, 'height': 720}}

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def create_dynamic_report(project: str, model: str, title: str, pages: list[ReportPage]) -> dict:
        """Create a NEW report from declarative pages and visuals on an enrolled live SSAS model. Never copies old pages/visuals, changes SSAS data, overwrites projects, builds or publishes. Use listed fields only; then inspect and build with returned revision."""
        result = creator.create(project, model, title, pages)
        result['revision'] = service.inspect(project)['revision']
        return result

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False})
    def update_dynamic_report(project: str, expected_revision: str, pages: list[ReportPage]) -> dict:
        """Replace page/visual definitions only in a creator-managed report; back up the previous layout and require current revision. Does not update a published report or the SSAS model. Provide the COMPLETE intended page list."""
        return creator.update(project, expected_revision, pages)

    @mcp.tool(annotations={'readOnlyHint': True})
    def inspect_headless_report(project: str) -> dict:
        """Inspect an enrolled legacy thin report and return a source revision. No model migration or server connectivity check."""
        return service.inspect(project)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def build_headless_report(project: str, expected_revision: str) -> dict:
        """Compile a reviewed thin report to a new unique PBIX without Desktop. Requires an external SSAS model. Does not save a Desktop process, migrate an embedded model, render, or publish."""
        return service.build(project, expected_revision)

    return mcp


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--http-port', type=int)
    args = parser.parse_args()
    settings = {}
    if args.http_port is not None:
        if not 1024 <= args.http_port <= 65535:
            parser.error('HTTP port must be between 1024 and 65535')
        # Remote access must go through the operator's authenticated proxy.
        settings = dict(host='127.0.0.1', port=args.http_port)
    build_mcp(json.loads(Path(args.config).read_text(encoding='utf-8-sig')), **settings).run(
        transport='streamable-http' if args.http_port is not None else 'stdio')
