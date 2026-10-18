"""Publish new reports only to explicitly enrolled destinations, without overwrite."""
import json
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from .core import identifier, sha256


def destination(service, actor, alias):
    client = service.authorize(actor, None, 'create')
    service.authorize(actor, None, 'read')
    target = service.config.get('new_report_destinations', {}).get(identifier(alias))
    if not target or alias not in client.get('create_reports', []) or alias not in client.get('reports', []):
        raise PermissionError('New report destination is not enrolled for this caller')
    folder, name = target['folder'], target['name']
    if (not folder.startswith('/') or folder.endswith('/') or any(p in ('', '.', '..') for p in folder[1:].split('/'))
            or any(c in folder for c in '\\?*<>:"\r\n') or not name or name in ('.', '..')
            or any(c in name for c in '\\/:?*<>"\r\n') or name != name.strip() or name.endswith('.')):
        raise ValueError('Invalid operator-enrolled catalog destination')
    return folder, name, folder + '/' + name


def ensure_absent(service, actor, path):
    items = service._call(actor, 'list')['reports']
    if any(item['Path'].casefold() == path.casefold() for item in items):
        raise PermissionError('Destination already exists; new-report publishing never overwrites')


def publish(service, actor, alias, file_name, approval_id):
    folder, name, target_path = destination(service, actor, alias)
    if not service.config.get('write_enabled'):
        raise PermissionError('Writes are disabled by the operator')
    if Path(file_name).name != file_name or '/' in file_name or '\\' in file_name:
        raise ValueError('Use a filename inside release_root')
    source = (service.release / file_name).resolve()
    if not source.is_relative_to(service.release) or source.suffix.lower() != '.pbix' or not source.is_file():
        raise ValueError('Existing PBIX inside release_root required')
    if source.stat().st_size > service.config.get('max_pbix_bytes', 2_000_000_000):
        raise ValueError('PBIX exceeds size limit')
    with service.lock(alias):
        prepared_dir = service.root / 'staging' / uuid.uuid4().hex
        prepared_dir.mkdir()
        try:
            prepared = prepared_dir / (name + '.pbix')
            shutil.copyfile(source, prepared)
            with zipfile.ZipFile(prepared) as archive:
                if archive.testzip() or 'Report/Layout' not in archive.namelist():
                    raise ValueError('Valid Power BI report ZIP required')
            digest = sha256(prepared)
            approval_path, approval = service._approved(actor, alias, approval_id, 'create', digest)
            if approval.get('target_path') != target_path:
                raise PermissionError('Approval does not match the enrolled destination path')
            ensure_absent(service, actor, target_path)
            if approval['expires_at'] <= time.time():
                raise PermissionError('Approval expired before creation')
            approval_path.rename(service.root / 'consumed' / approval_path.name)
            try:
                item = service._call(actor, 'create', folder=folder, name=name, source=str(prepared))['report']
                report_id = str(uuid.UUID(item['Id']))
                catalog_item = service._call(actor, 'get', report_id=report_id)['report']
                if catalog_item['Path'] != target_path:
                    raise RuntimeError('Created catalog path differs from the approved destination')
                record = service.root / 'catalog-enrollments' / (identifier(alias) + '.json')
                pending = record.with_suffix('.tmp')
                pending.write_text(json.dumps({'id': report_id, 'path': target_path}), encoding='utf-8')
                pending.replace(record)
                verified = prepared_dir / 'downloaded.pbix'
                service._call(actor, 'download', report_id=report_id, destination=str(verified))
                matches = sha256(verified) == digest
                return {'status': 'verified' if matches else 'verification_mismatch', 'sha256': digest,
                    'report_id': report_id, 'created': True, 'render_verified': False,
                    **service.get_report_link(actor, alias)}
            except Exception:
                raise RuntimeError('New report creation/verification outcome may be uncertain; approval consumed. '
                    'Inspect the enrolled catalog path before any retry: ' + target_path) from None
        finally:
            shutil.rmtree(prepared_dir)
