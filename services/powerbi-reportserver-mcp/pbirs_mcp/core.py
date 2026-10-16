from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from .observability import current_session_id, current_traceparent
from .otel_tracing import child_span

log = logging.getLogger(__name__)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def identifier(value: str) -> str:
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('Invalid identifier')
    return value


class PowerShellBackend:
    def __init__(self, portal: str, credential_path=None, executable: str = 'powershell.exe'):
        self.portal, self.executable, self.credential_path = portal, executable, credential_path

    def call(self, operation: str, **kwargs):
        request = dict(operation=operation, portal=self.portal, credential_path=self.credential_path, **kwargs,
                       traceparent=current_traceparent(), session_id=current_session_id())
        with child_span('pbirs.' + operation):
            result = subprocess.run(
                [self.executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                 str(Path(__file__).with_name('bridge.ps1'))],
                input=json.dumps(request), text=True, encoding='utf-8',
                capture_output=True, timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        try:
            data = json.loads(result.stdout.lstrip('\ufeff'))
        except (ValueError, TypeError):
            raise RuntimeError('PowerShell bridge failed; verify module installation and Windows identity') from None
        if result.returncode or 'error' in data:
            raise RuntimeError('PBIRS failure: ' + str(data.get('http_status')) + ' ' + str(data.get('exception_type')) + ' code=' + str(data.get('upstream_code')) + ' network=' + str(data.get('network_status')))
        return data


class Service:
    def __init__(self, config: dict, backend=None):
        self.config = config
        portal = config['portal'].rstrip('/')
        parsed = urlsplit(portal)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('Invalid configured portal URL')
        self.portal = portal
        self.backend = backend or PowerShellBackend(portal, config.get('credential_path'))
        self.root = Path(config['data_root']).resolve()
        self.release = Path(config['release_root']).resolve()
        for folder in ('backups', 'approvals', 'consumed', 'staging', 'locks'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.release.mkdir(parents=True, exist_ok=True)
        for alias, report_id in config.get('reports', {}).items():
            identifier(alias)
            uuid.UUID(report_id)

    def authorize(self, actor: str, report: str | None, scope: str):
        client = self.config.get('clients', {}).get(actor)
        if not client or scope not in client.get('scopes', []):
            raise PermissionError('Operation not permitted')
        if report is not None and (report not in client.get('reports', []) or report not in self.config['reports']):
            raise PermissionError('Report not permitted')
        return client

    def _call(self, actor, operation, **kwargs):
        if isinstance(self.backend, PowerShellBackend):
            client = self.config['clients'][actor]
            credential_path = client.get('credential_path')
            if actor != 'local-operator' and not credential_path:
                raise PermissionError('Personal Windows credential mapping required for this caller')
            backend = PowerShellBackend(self.portal, credential_path or self.config.get('credential_path'))
            return backend.call(operation, **kwargs)
        return self.backend.call(operation, **kwargs)

    def list_reports(self, actor):
        client = self.authorize(actor, None, 'read')
        if not client.get('reports'):
            return []
        catalog = self._call(actor, 'list')['reports']
        allowed = {v: k for k, v in self.config['reports'].items() if k in client.get('reports', [])}
        return [dict(alias=allowed[str(x['Id'])], name=x['Name'], path=x['Path'])
                for x in catalog if str(x['Id']) in allowed]

    def get_report_link(self, actor, report):
        self.authorize(actor, report, 'read')
        item = self._call(actor, 'get', report_id=self.config['reports'][report])['report']
        path = item['Path']
        if not path.startswith('/'):
            raise RuntimeError('Invalid catalog path')
        url = self.portal + '/powerbi' + quote(path, safe='/')
        return dict(report=report, url=url, embed_url=url + '?rs:embed=true')

    @contextmanager
    def lock(self, report):
        path = self.root / 'locks' / (identifier(report) + '.lock')
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError('Report is busy or has an unresolved interrupted operation') from None
        os.close(fd)
        try:
            yield
        finally:
            path.unlink()

    def _backup(self, actor, report):
        backup_id = uuid.uuid4().hex
        path = self.root / 'backups' / (backup_id + '.pbix')
        self._call(actor, 'download', report_id=self.config['reports'][report], destination=str(path))
        digest = sha256(path)
        meta = dict(backup_id=backup_id, report=report, sha256=digest, created_at=time.time())
        path.with_suffix('.json').write_text(json.dumps(meta), encoding='utf-8')
        return meta

    def download_report_backup(self, actor, report):
        self.authorize(actor, report, 'backup')
        with self.lock(report):
            return self._backup(actor, report)

    def _approved(self, actor, report, approval_id, action, digest):
        path = self.root / 'approvals' / (identifier(approval_id) + '.json')
        try:
            approval = json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            raise PermissionError('Valid operator approval required') from None
        if (approval.get('actor') != actor or approval.get('report') != report or approval.get('action') != action
                or approval.get('sha256') != digest or approval.get('expires_at', 0) <= time.time()):
            raise PermissionError('Approval does not match actor, report, action, hash or expiry')
        return path, approval

    def _publish(self, actor, report, source, approval_id, action):
        self.authorize(actor, report, 'publish')
        self.authorize(actor, report, 'read')
        if not self.config.get('write_enabled', False):
            raise PermissionError('Writes are disabled by the operator')
        if source.suffix.lower() != '.pbix' or not source.is_file():
            raise ValueError('Existing PBIX file required')
        if source.stat().st_size > self.config.get('max_pbix_bytes', 2_000_000_000):
            raise ValueError('PBIX exceeds configured size limit')
        with self.lock(report):
            staging = self.root / 'staging' / uuid.uuid4().hex
            staging.mkdir()
            try:
                item = self._call(actor, 'get', report_id=self.config['reports'][report])['report']
                name = item['Name']
                if not name or any(c in name for c in '<>:"/\\|?*') or name in ('.', '..'):
                    raise ValueError('Unsafe report name from catalog')
                prepared = staging / (name + '.pbix')
                shutil.copyfile(source, prepared)
                if not zipfile.is_zipfile(prepared):
                    raise ValueError('PBIX must be a ZIP-based Power BI file')
                digest = sha256(prepared)
                approval_path, approval = self._approved(actor, report, approval_id, action, digest)
                backup = self._backup(actor, report)
                if backup['sha256'] != approval.get('expected_current_sha256'):
                    raise PermissionError('Report changed since review; obtain a fresh approval')
                if approval['expires_at'] <= time.time():
                    raise PermissionError('Approval expired while preparing the backup')
                # One attempt per approval, including uncertain upload outcomes. Never blindly retry writes.
                approval_path.rename(self.root / 'consumed' / approval_path.name)
                log.info('pbirs_publish_started', extra={'stair.actor': actor, 'stair.report': report,
                         'stair.approval.id': approval_id, 'stair.backup.id': backup['backup_id']})
                try:
                    self._call(actor, 'upload', report_id=self.config['reports'][report], source=str(prepared))
                    verified = staging / 'verification.pbix'
                    self._call(actor, 'download', report_id=self.config['reports'][report], destination=str(verified))
                    matches = sha256(verified) == digest
                except Exception as error:
                    log.error('pbirs_publish_outcome_uncertain', extra={'stair.actor': actor, 'stair.report': report,
                              'stair.backup.id': backup['backup_id']})
                    diagnostic = str(error) if re.fullmatch(r'PBIRS failure: [A-Za-z0-9_. =-]+', str(error)) else 'See local diagnostics'
                    raise RuntimeError('Upload/verification failed. Outcome may be uncertain; approval consumed. '
                                       'Inspect report before retry; backup_id=' + backup['backup_id'] + '; ' + diagnostic) from None
                result = dict(status='verified' if matches else 'verification_mismatch', sha256=digest,
                              backup_id=backup['backup_id'], **self.get_report_link(actor, report))
                log.info('pbirs_publish_finished', extra={'stair.actor': actor, 'stair.report': report,
                         'stair.publish.status': result['status']})
                return result
            finally:
                shutil.rmtree(staging)

    def publish_reviewed_pbix(self, actor, report, file_name, approval_id):
        if Path(file_name).name != file_name or '/' in file_name or '\\' in file_name:
            raise ValueError('Use a filename within release_root')
        source = (self.release / file_name).resolve()
        if not source.is_relative_to(self.release):
            raise ValueError('File must remain inside release_root')
        return self._publish(actor, report, source, approval_id, 'publish')

    def restore_previous_pbix(self, actor, report, backup_id, approval_id):
        self.authorize(actor, report, 'publish')
        identifier(backup_id)
        path = self.root / 'backups' / (backup_id + '.pbix')
        metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if metadata['report'] != report or sha256(path) != metadata['sha256']:
            raise PermissionError('Backup does not match report or hash')
        return self._publish(actor, report, path, approval_id, 'restore')
