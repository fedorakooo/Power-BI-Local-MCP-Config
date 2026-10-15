"""Schema-validated PBIR visual authoring for explicitly enrolled local projects."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import jsonschema
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from referencing import Registry, Resource

BASE = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/'
SCHEMAS = Path(__file__).resolve().parents[1] / 'schemas'


class MeasureCard(BaseModel):
    table: str = Field(min_length=1, max_length=100)
    measure: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)


def literal(value):
    return {'expr': {'Literal': {'Value': value}}}


def text_literal(value):
    return literal("'" + value.replace("'", "''") + "'")


def binding(table, name, kind):
    return {kind: {'Expression': {'SourceRef': {'Entity': table}}, 'Property': name}}


def container(name, kind, position, role, table, field, label, field_kind='Measure'):
    return {'$schema': BASE + 'visualContainer/2.12.0/schema.json', 'name': name,
        'position': dict(x=position[0], y=position[1], width=position[2], height=position[3], z=0, tabOrder=0),
        'visual': {'visualType': kind, 'query': {'queryState': {role: {'projections': [
            {'field': binding(table, field, field_kind), 'queryRef': table + '.' + field,
             'nativeQueryRef': label, 'displayName': label}]}}},
            'visualContainerObjects': {'title': [{'properties': {'show': literal('true'),
                'text': text_literal(label), 'fontSize': literal('16D')}}]},
            'drillFilterOtherVisuals': True}}


class Authoring:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['data_root']).resolve() / 'authoring'
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = json.loads((SCHEMAS / 'manifest.json').read_text())
        self.schemas = {}
        for uri, entry in manifest.items():
            payload = (SCHEMAS / entry['file']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != entry['sha256']:
                raise RuntimeError('Vendored schema checksum mismatch')
            self.schemas[uri] = json.loads(payload)
        self.registry = Registry().with_resources((uri, Resource.from_contents(doc)) for uri, doc in self.schemas.items())

    def validate(self, document):
        schema = self.schemas.get(document.get('$schema'))
        if not schema:
            raise ValueError('Unsupported schema version; review and vendor it before writing')
        jsonschema.Draft202012Validator(schema, registry=self.registry).validate(document)

    def project(self, alias):
        entry = self.config.get('authoring_projects', {}).get(alias)
        if not entry:
            raise PermissionError('Project is not enrolled')
        pbip = Path(entry).resolve()
        document = json.loads(pbip.read_text(encoding='utf-8-sig'))
        artifacts = document.get('artifacts', [])
        if len(artifacts) != 1:
            raise ValueError('Expected one report artifact')
        report = (pbip.parent / artifacts[0]['report']['path']).resolve()
        if not report.is_relative_to(pbip.parent):
            raise ValueError('Report reference escapes the enrolled project')
        pbir = json.loads((report / 'definition.pbir').read_text())
        model = (report / pbir['datasetReference']['byPath']['path']).resolve()
        if not model.is_relative_to(pbip.parent):
            raise ValueError('Semantic model reference escapes the enrolled project')
        if not (report / 'definition/pages').is_dir():
            raise ValueError('PBIR is required; PBIR-Legacy is not edited')
        return pbip, report, model

    def files(self, alias):
        pbip, report, model = self.project(alias)
        files = [pbip, report / 'definition.pbir', *sorted((report / 'definition').rglob('*.json')),
                 *sorted((model / 'definition').rglob('*.tmdl'))]
        for file in files:
            if not file.resolve().is_relative_to(pbip.parent):
                raise ValueError('Project contains an external symlink or junction')
        return files

    def revision(self, alias):
        pbip, _, _ = self.project(alias)
        digest = hashlib.sha256()
        for file in self.files(alias):
            digest.update(file.relative_to(pbip.parent).as_posix().encode())
            digest.update(hashlib.sha256(file.read_bytes()).digest())
        return digest.hexdigest()

    def inspect(self, alias):
        pbip, report, _ = self.project(alias)
        pages = []
        for path in sorted((report / 'definition/pages').glob('*/page.json')):
            page = json.loads(path.read_text())
            visuals = []
            for file in sorted((path.parent / 'visuals').glob('*/visual.json')):
                visual = json.loads(file.read_text())
                visuals.append({'id': visual['name'], 'type': visual.get('visual', {}).get('visualType'),
                                'position': visual.get('position')})
            pages.append({'id': page['name'], 'title': page['displayName'], 'visuals': visuals})
        return {'project': alias, 'pbip': str(pbip), 'revision': self.revision(alias), 'pages': pages}

    @contextmanager
    def lock(self, alias):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}', alias):
            raise ValueError('Invalid alias')
        lock = self.root / (alias + '.lock')
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def field_exists(self, model, table, name, kind):
        quoted = "'" + name.replace("'", "''") + "'"
        table_quoted = "'" + table.replace("'", "''") + "'"
        for file in (model / 'definition/tables').glob('*.tmdl'):
            content = file.read_text(encoding='utf-8-sig')
            if not re.search(r'^table\s+(?:' + re.escape(table_quoted) + '|' + re.escape(table) + r')\s*$', content, re.M):
                continue
            if re.search(r'^\t' + kind + r'\s+(?:' + re.escape(quoted) + '|' + re.escape(name) + r')(?=\s*(?:=|\r?$))', content, re.M):
                return True
        return False

    def add_dashboard(self, alias, expected_revision, title, cards, slicer_table, slicer_column):
        if not 1 <= len(cards) <= 3 or not 1 <= len(title) <= 100:
            raise ValueError('Provide a page title and 1-3 KPI cards')
        with self.lock(alias):
            if self.revision(alias) != expected_revision:
                raise ValueError('Project changed; inspect again before writing')
            pbip, report, model = self.project(alias)
            pages_file = report / 'definition/pages/pages.json'
            pages = json.loads(pages_file.read_text())
            for old in (report / 'definition/pages').glob('*/page.json'):
                if json.loads(old.read_text()).get('displayName') == title:
                    raise ValueError('Page title already exists; refusing duplicate creation')
            for card in cards:
                if not self.field_exists(model, card.table, card.measure, 'measure'):
                    raise ValueError('Measure must exist in the saved project: ' + card.table + '[' + card.measure + ']')
            if not self.field_exists(model, slicer_table, slicer_column, 'column'):
                raise ValueError('Slicer column is missing from the saved model')
            page_id = uuid.uuid4().hex[:20]
            folder = pages_file.parent / page_id
            page = {'$schema': BASE + 'page/2.1.0/schema.json', 'name': page_id, 'displayName': title,
                    'displayOption': 'FitToPage', 'width': 1280, 'height': 720}
            generated = {folder / 'page.json': page}
            for index, card in enumerate(cards):
                visual_id = uuid.uuid4().hex[:20]
                visual = container(visual_id, 'card', (48 + index * 400, 180, 368, 200),
                                   'Values', card.table, card.measure, card.title)
                visual['visual']['objects'] = {
                    'labels': [{'properties': {'fontSize': literal('42D'), 'labelDisplayUnits': literal('0D')}}],
                    'categoryLabels': [{'properties': {'show': literal('false')}}]}
                generated[folder / 'visuals' / visual_id / 'visual.json'] = visual
            visual_id = uuid.uuid4().hex[:20]
            slicer = container(visual_id, 'slicer', (48, 40, 440, 110), 'Values',
                               slicer_table, slicer_column, 'Filter by manager', 'Column')
            slicer['visual']['objects'] = {'data': [{'properties': {'mode': text_literal('Dropdown')}}]}
            generated[folder / 'visuals' / visual_id / 'visual.json'] = slicer
            pages['pageOrder'].append(page_id)
            pages['activePageName'] = page_id
            generated[pages_file] = pages
            for document in generated.values():
                self.validate(document)
            backup_id = uuid.uuid4().hex
            with zipfile.ZipFile(self.root / (backup_id + '.zip'), 'x', zipfile.ZIP_DEFLATED) as archive:
                for file in self.files(alias):
                    archive.write(file, file.relative_to(pbip.parent))
            # Install newly named files first, commit the page index last. No existing
            # visual/page definitions are overwritten; the pre-change project is backed up.
            for path, document in generated.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix('.tmp-' + backup_id)
                temp.write_text(json.dumps(document, indent=2), encoding='utf-8')
                os.replace(temp, path)
            result = {'status': 'project_files_updated', 'project': alias, 'page_id': page_id,
                      'page_title': title, 'backup_id': backup_id, 'revision': self.revision(alias),
                      'visual_count': len(cards) + 1, 'desktop_reload_required': True}
            (self.root / (backup_id + '.audit.json')).write_text(json.dumps(result, indent=2))
            return result

    def add_ratio_measure(self, alias, expected_revision, table, name, numerator, denominator):
        if any(not 1 <= len(v) <= 100 or any(c in v for c in '\r\n\x00') for v in [table, name, numerator, denominator]):
            raise ValueError('Invalid measure identifiers')
        with self.lock(alias):
            if self.revision(alias) != expected_revision:
                raise ValueError('Project changed; inspect again')
            pbip, _, model = self.project(alias)
            if self.field_exists(model, table, name, 'measure'):
                raise ValueError('Measure exists; refusing to overwrite')
            for field in [numerator, denominator]:
                if not self.field_exists(model, table, field, 'measure'):
                    raise ValueError('Referenced measure does not exist in the target table')
            quoted_table = "'" + table.replace("'", "''") + "'"
            candidates = [p for p in (model / 'definition/tables').glob('*.tmdl') if
                re.search(r'^table\s+(?:' + re.escape(quoted_table) + '|' + re.escape(table) + r')\s*$',
                          p.read_text(encoding='utf-8-sig'), re.M)]
            if len(candidates) != 1:
                raise ValueError('Expected one table definition')
            path = candidates[0]
            backup_id = uuid.uuid4().hex
            with zipfile.ZipFile(self.root / (backup_id + '.zip'), 'x', zipfile.ZIP_DEFLATED) as archive:
                for file in self.files(alias):
                    archive.write(file, file.relative_to(pbip.parent))
            expression = 'DIVIDE([' + numerator.replace(']', ']]') + '], [' + denominator.replace(']', ']]') + '], 0)'
            definition = ("\n\tmeasure '" + name.replace("'", "''") + "' = " + expression +
                          '\n\t\tformatString: 0.00%\n\t\tdisplayFolder: Fedaraka MCP\n\t\tlineageTag: ' + str(uuid.uuid4()) + '\n')
            temporary = path.with_suffix('.tmp-' + backup_id)
            temporary.write_text(path.read_text(encoding='utf-8-sig').rstrip() + '\n' + definition, encoding='utf-8')
            os.replace(temporary, path)
            result = {'status': 'saved_measure_definition_updated', 'measure': name, 'expression': expression,
                      'backup_id': backup_id, 'revision': self.revision(alias), 'desktop_reload_required': True,
                      'verification_required': 'Reload project in Desktop; verify measure Ready and evaluate it through modeling MCP.'}
            (self.root / (backup_id + '.audit.json')).write_text(json.dumps(result, indent=2))
            return result


def build(config):
    service = Authoring(config)
    mcp = FastMCP('Power BI Report Authoring')

    @mcp.tool(annotations={'readOnlyHint': True})
    def inspect_report_project(project: str) -> dict:
        """Inspect an enrolled PBIP/PBIR report's pages and visuals; return revision for conflict detection."""
        return service.inspect(project)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def add_kpi_dashboard(project: str, expected_revision: str, title: str, cards: list[MeasureCard],
                          slicer_table: str, slicer_column: str) -> dict:
        """Add a page with 1-3 bound KPI cards and an interactive column slicer. Validate generated PBIR
        against pinned Microsoft schemas, back up, and reject stale revisions/unknown fields/duplicate pages.
        Changes are project files; use the Computer Use MCP to reload Desktop, inspect rendering, save a
        new PBIX release copy and verify it. Never claim a file edit is a rendered or published report.
        """
        return service.add_dashboard(project, expected_revision, title, cards, slicer_table, slicer_column)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def add_project_ratio_measure(project: str, expected_revision: str, table: str, measure_name: str,
                                   numerator_measure: str, denominator_measure: str) -> dict:
        """Persist a new percentage ratio measure in the enrolled project's TMDL, with backup and revision check.
        Numerator and denominator must be existing measures in that table. Does not overwrite a measure.
        Reload and verify through Desktop/modeling MCP before claiming success; never save a stale open model.
        """
        return service.add_ratio_measure(project, expected_revision, table, measure_name, numerator_measure, denominator_measure)

    @mcp.tool(annotations={'readOnlyHint': True})
    def verify_saved_report(file_name: str) -> dict:
        """Verify a saved release PBIX is a readable ZIP, with Report definition and embedded model.
        Does not prove compatibility with Power BI Report Server or publish anything.
        """
        from .core import sha256
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,100}\.pbix', file_name, re.I):
            raise ValueError('Use a simple PBIX name')
        root = Path(config['release_root']).resolve()
        path = (root / file_name).resolve()
        if path.parent != root:
            raise PermissionError('Release path escapes configured folder')
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if archive.testzip() is not None or not any(n.startswith('Report/') for n in names) or 'DataModel' not in names:
                raise ValueError('Saved PBIX is incomplete')
        return {'status': 'saved_pbix_verified', 'path': str(path), 'file_name': file_name,
                'bytes': path.stat().st_size, 'sha256': sha256(path)}

    @mcp.tool(annotations={'readOnlyHint': True})
    def get_report_automation_workflow(project: str) -> dict:
        """Return the complete agent workflow, including Desktop actions via Computer Use MCP.
        Requires Codex Computer Use and unlocked Windows; this authoring server does not bypass its approvals.
        """
        pbip, _, _ = service.project(project)
        return {'project_path': str(pbip), 'release_root': config['release_root'], 'steps': [
            'Use modeling MCP for model inspection and approved changes. Ensure measures exist in saved project before binding visuals.',
            'Inspect project revision, then add_kpi_dashboard with reviewed measure/column bindings.',
            'Use Codex Computer Use MCP to apply the Desktop external-change reload prompt; if absent, reopen the PBIP through Desktop File Open.',
            'Observe the new page, select a slicer value and verify KPI values change; reset to All.',
            'Use Computer Use MCP File Save As to save a uniquely named PBIX in release_root, then call verify_saved_report.',
            'For Report Server, first prove Desktop/PBIX version compatibility on a staging report. Obtain one-use operator approval, then use publisher MCP; return its verified catalog links.'],
            'constraints': ['PBIP is unsupported in Desktop for Report Server; use an explicitly validated compatible artifact pipeline before deployment.',
                            'No unattended Windows service GUI: interactive unlocked user session is required.',
                            'Do not automate credentials, access/security settings, unknown dialogs or blind retries of writes.']}

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    build(json.loads(Path(args.config).read_text(encoding='utf-8-sig'))).run(transport='stdio')


if __name__ == '__main__':
    main()
