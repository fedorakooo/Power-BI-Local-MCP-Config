"""Create and revise bounded legacy thin reports on operator-enrolled SSAS models."""
from __future__ import annotations
import copy
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    table: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)


class ReportVisual(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['card', 'columnChart', 'slicer']
    title: str = Field(min_length=1, max_length=100)
    measure: ReportField | None = None
    category: ReportField | None = None
    x: int = Field(ge=0, le=1280)
    y: int = Field(ge=0, le=720)
    width: int = Field(ge=100, le=1280)
    height: int = Field(ge=60, le=720)

    @model_validator(mode='after')
    def validate_binding(self):
        if self.x + self.width > 1280 or self.y + self.height > 720:
            raise ValueError('Visual must fit the 1280x720 canvas')
        if self.type in ('card', 'columnChart') and not self.measure:
            raise ValueError('This visual requires a measure')
        if self.type in ('slicer', 'columnChart') and not self.category:
            raise ValueError('This visual requires a category column')
        if (self.type == 'card' and self.category) or (self.type == 'slicer' and self.measure):
            raise ValueError('Unexpected field binding for this visual')
        return self


class ReportPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=100)
    visuals: list[ReportVisual] = Field(min_length=1, max_length=20)


def literal(value):
    return {'expr': {'Literal': {'Value': value}}}


def text(value):
    return literal("'" + value.replace("'", "''") + "'")


def color(value):
    return {'solid': {'color': text(value)}}


def visual_document(spec, schema, ordinal):
    fields = []
    if spec.category:
        fields.append(('Category' if spec.type == 'columnChart' else 'Values', spec.category, 'Column'))
    if spec.measure:
        fields.append(('Y' if spec.type == 'columnChart' else 'Values', spec.measure, 'Measure'))
    tables = list(dict.fromkeys(field.table for _, field, _ in fields))
    aliases = {table: 't' + str(i) for i, table in enumerate(tables)}
    projections, selects, metadata, transforms, roles = {}, [], [], [], []
    for index, (role, field, kind) in enumerate(fields):
        query_ref = field.table + '.' + field.name
        expression = {kind: {'Expression': {'SourceRef': {'Source': aliases[field.table]}}, 'Property': field.name}}
        entity_expression = {kind: {'Expression': {'SourceRef': {'Entity': field.table}}, 'Property': field.name}}
        projections[role] = [{'queryRef': query_ref, **({'active': True} if kind == 'Column' else {})}]
        selects.append(dict(expression, Name=query_ref, NativeReferenceName=field.name))
        item = {'Restatement': field.name, 'Name': query_ref, 'Type': 2048 if kind == 'Column' else 3}
        field_settings = schema[field.table]['columns' if kind == 'Column' else 'measures'][field.name]
        fmt = field_settings.get('format')
        if fmt:
            item['Format'] = fmt
        metadata.append(item)
        selection = {'displayName': field.name, 'queryName': query_ref, 'roles': {role: True},
            'type': {'category': None, 'underlyingType': 1 if kind == 'Column' else 260}, 'expr': entity_expression}
        if fmt:
            selection['format'] = fmt
        transforms.append(selection)
        roles.append({'Name': role, 'Projection': index, 'isActive': kind == 'Column'})
    query = {'Version': 2, 'From': [{'Name': aliases[t], 'Entity': t, 'Type': 0} for t in tables], 'Select': selects}
    objects = {}
    if spec.type == 'card':
        objects = {'labels': [{'properties': {'fontSize': literal('40D'), 'labelDisplayUnits': literal('0D')}}],
                   'categoryLabels': [{'properties': {'show': literal('false')}}]}
    elif spec.type == 'slicer':
        objects = {'data': [{'properties': {'mode': text('Dropdown')}}]}
    position = dict(x=spec.x, y=spec.y, z=ordinal * 1000, width=spec.width, height=spec.height, tabOrder=ordinal)
    visual = {'visualType': spec.type, 'projections': projections, 'prototypeQuery': query,
        'drillFilterOtherVisuals': True, 'objects': objects, 'vcObjects': {
            'title': [{'properties': {'show': literal('true'), 'text': text(spec.title), 'fontSize': literal('16D')}}],
            'background': [{'properties': {'show': literal('true'), 'color': color('#FFFFFF'), 'transparency': literal('0D')}}]}}
    config = {'name': uuid.uuid4().hex[:20], 'layouts': [{'id': 0, 'position': position}], 'singleVisual': visual}
    binding = {'Primary': {'Groupings': [{'Projections': list(range(len(selects)))}]},
        'DataReduction': {'DataVolume': 3, 'Primary': {'Top': {}} if spec.type == 'card' else {'Window': {'Count': 1000}}}, 'Version': 1}
    if spec.type == 'slicer':
        binding['IncludeEmptyGroups'] = True
    data_transforms = {'objects': objects, 'projectionOrdering': {role: [i] for i, (role, _, _) in enumerate(fields)},
        'queryMetadata': {'Select': metadata}, 'visualElements': [{'DataRoles': roles}], 'selects': transforms}
    return dict(position, config=json.dumps(config), filters='[]',
        query=json.dumps({'Commands': [{'SemanticQueryDataShapeCommand': {'Query': query, 'Binding': binding, 'ExecutionMetricsKind': 1}}]}),
        dataTransforms=json.dumps(data_transforms))


class DynamicReports:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['headless_creation_root']).resolve() if config.get('headless_creation_root') else None

    def profile(self, name):
        profile = self.config.get('headless_creation_profiles', {}).get(name)
        if not profile or not profile.get('schema'):
            raise PermissionError('SSAS creation model is not enrolled with a field schema')
        return profile

    def models(self):
        return [{'model': name, 'description': profile.get('description', ''), 'schema': profile['schema'],
                 'live_connection': True} for name, profile in self.config.get('headless_creation_profiles', {}).items()]

    def path(self, project):
        if not self.root or not re.fullmatch(r'[a-z][a-z0-9-]{0,59}', project):
            raise PermissionError('Report creation is not configured or project alias is invalid')
        if project in self.config.get('headless_projects', {}):
            raise PermissionError('Existing operator-enrolled projects cannot be replaced by the creator')
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / project
        if target.is_symlink() or (target.exists() and getattr(target.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Managed project links are not permitted')
        return target

    @contextmanager
    def lock(self, project):
        target = self.path(project)
        lock = self.root / (project + '.lock')
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        try:
            yield target
        finally:
            lock.unlink()

    def entry(self, project):
        target = self.path(project)
        meta = json.loads((target / '.mcp-created-report.json').read_text())
        if meta.get('project') != project or meta.get('creator') != 'powerbi-dynamic-reports-v1':
            raise PermissionError('Report is not managed by this creator')
        profile = self.profile(meta['model'])
        return dict(source_root=str(target), report_version=profile['report_version'], connection_string=profile['connection_string'])

    def layout(self, profile, pages):
        if not 1 <= len(pages) <= 8 or len({p.title for p in pages}) != len(pages):
            raise ValueError('Provide 1-8 pages with unique titles')
        for page in pages:
            for visual in page.visuals:
                for field, kind in [(visual.category, 'columns'), (visual.measure, 'measures')]:
                    if field and field.name not in profile['schema'].get(field.table, {}).get(kind, {}):
                        raise ValueError('Field is not in the operator-enrolled SSAS schema: ' + field.table + '[' + field.name + ']')
        baseline = json.loads((Path(profile['compatibility_source']) / 'Report/report.json').read_text(encoding='utf-8-sig'))
        baseline_config = json.loads(baseline.get('config', '{}'))
        report = {'id': 0, 'resourcePackages': copy.deepcopy(baseline.get('resourcePackages', [])),
            'config': json.dumps({'version': baseline_config.get('version', '5.68'),
                'themeCollection': baseline_config.get('themeCollection', {}), 'activeSectionIndex': 0, 'bookmarks': []}),
            'filters': '[]', 'sections': []}
        for index, page in enumerate(pages):
            report['sections'].append({'name': 'ReportSection' + uuid.uuid4().hex[:20], 'displayName': page.title,
                'filters': '[]', 'ordinal': index, 'displayOption': 1, 'width': 1280, 'height': 720,
                'config': json.dumps({'objects': {'background': [{'properties': {'color': color('#F1F5F9'), 'transparency': literal('0D')}}]}}),
                'visualContainers': [visual_document(v, profile['schema'], n) for n, v in enumerate(page.visuals)]})
        return report

    def create(self, project, model, title, pages):
        if not 1 <= len(title) <= 100:
            raise ValueError('Report title must be 1-100 characters')
        profile = self.profile(model)
        layout = self.layout(profile, pages)
        with self.lock(project) as destination:
            if destination.exists():
                raise FileExistsError('Report project already exists; inspect and update it instead')
            pending = self.root / ('.pending-' + uuid.uuid4().hex)
            pending.mkdir()
            try:
                source = Path(profile['compatibility_source']).resolve()
                # Reuse only compatibility metadata/theme files, never old report pages or visuals.
                for name in ('Version.txt', 'ReportMetadata.json', 'ReportSettings.json', '.pbixproj.json'):
                    shutil.copyfile(source / name, pending / name)
                if (source / 'StaticResources').exists():
                    shutil.copytree(source / 'StaticResources', pending / 'StaticResources')
                (pending / 'Report').mkdir()
                (pending / 'Report/report.json').write_text(json.dumps(layout), encoding='utf-8')
                (pending / 'Connections.json').write_text(json.dumps({'Version': 1, 'Connections': [{
                    'Name': 'EntityDataSource', 'ConnectionType': 'analysisServicesDatabaseLive',
                    'ConnectionString': profile['connection_string']}]}), encoding='utf-8')
                (pending / '.mcp-created-report.json').write_text(json.dumps({'creator': 'powerbi-dynamic-reports-v1',
                    'project': project, 'model': model, 'title': title}), encoding='utf-8')
                destination.parent.mkdir(parents=True, exist_ok=True)
                pending.rename(destination)
            finally:
                if pending.exists():
                    shutil.rmtree(pending)
        return {'status': 'report_source_created', 'project': project, 'title': title, 'model': model,
                'pages': len(pages), 'visuals': sum(len(p.visuals) for p in pages), 'published': False}

    def update(self, project, expected_revision, pages):
        from .headless_build import revision
        with self.lock(project) as target:
            self.entry(project)
            if revision(target) != expected_revision:
                raise ValueError('Project changed; inspect again before updating')
            meta = json.loads((target / '.mcp-created-report.json').read_text())
            layout = self.layout(self.profile(meta['model']), pages)
            report = target / 'Report/report.json'
            backup_id = uuid.uuid4().hex
            backups = self.root / '.backups'
            backups.mkdir(exist_ok=True)
            shutil.copyfile(report, backups / (backup_id + '.json'))
            pending = report.with_suffix('.tmp')
            pending.write_text(json.dumps(layout), encoding='utf-8')
            os.replace(pending, report)
            return {'status': 'report_source_updated', 'project': project, 'backup_id': backup_id,
                'revision': revision(target), 'published': False}
