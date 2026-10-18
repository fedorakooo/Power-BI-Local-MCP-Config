"""Operator-only CLI. Never expose these commands as MCP tools."""
import argparse
import hashlib
import json
import secrets
import time
from pathlib import Path

from .core import Service, identifier, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.local.json')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--portal', default='http://report-server.example.com/Reports')
    sub.add_parser('discover')
    enroll = sub.add_parser('enroll')
    enroll.add_argument('--alias', required=True)
    enroll.add_argument('--report-id', required=True)
    approve = sub.add_parser('approve')
    approve.add_argument('--actor', default='local-operator')
    approve.add_argument('--report', required=True)
    approve.add_argument('--action', choices=['publish', 'restore'], required=True)
    approve.add_argument('--file', required=True)
    approve.add_argument('--expected-current-sha256', required=True)
    enroll_new = sub.add_parser('enroll-new')
    enroll_new.add_argument('--alias', required=True)
    enroll_new.add_argument('--folder', required=True)
    enroll_new.add_argument('--name', required=True)
    enroll_new.add_argument('--actor', required=True)
    approve_create = sub.add_parser('approve-create')
    approve_create.add_argument('--actor', required=True)
    approve_create.add_argument('--report', required=True)
    approve_create.add_argument('--file', required=True)
    args = parser.parse_args()
    path = Path(args.config).resolve()
    if args.command == 'init':
        if path.exists():
            raise SystemExit('Config already exists; refusing to replace credentials/settings')
        root = path.parent / 'runtime'
        token = secrets.token_urlsafe(48)
        config = dict(portal=args.portal, data_root=str(root), release_root=str(root / 'release'),
                      write_enabled=False, reports={}, clients={'local-operator': {
                          'token_sha256': hashlib.sha256(token.encode()).hexdigest(),
                          'scopes': ['read', 'backup', 'publish'], 'reports': []}})
        root.mkdir(parents=True, exist_ok=True)
        (root / 'operator-token.txt').write_text(token, encoding='utf-8')
        path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        Service(config)
        print('Initialized read-only configuration. Token saved privately in runtime/operator-token.txt.')
        return
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    service = Service(config)
    if args.command == 'discover':
        print(json.dumps(service.backend.call('list'), ensure_ascii=False, indent=2))
    elif args.command == 'enroll-new':
        from .new_reports import destination
        alias = identifier(args.alias)
        if alias in config.get('reports', {}) or alias in config.get('new_report_destinations', {}):
            raise SystemExit('Destination alias exists; refusing to overwrite enrollment')
        client = config['clients'].get(args.actor)
        if not client:
            raise SystemExit('Actor is not enrolled')
        config.setdefault('new_report_destinations', {})[alias] = dict(folder=args.folder, name=args.name)
        client.setdefault('create_reports', []).append(alias)
        if 'create' not in client['scopes']:
            client['scopes'].append('create')
        if alias not in client['reports']:
            client['reports'].append(alias)
        destination(Service(config), args.actor, alias)
        path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        print('New report destination enrolled. Restart MCP to apply.')
    elif args.command == 'approve-create':
        from .new_reports import destination, ensure_absent
        _, _, target_path = destination(service, args.actor, args.report)
        source = Path(args.file).resolve()
        if not source.is_relative_to(service.release) or source.suffix.lower() != '.pbix' or not source.is_file():
            raise SystemExit('Approval requires an existing PBIX inside release_root')
        ensure_absent(service, args.actor, target_path)
        approval_id = secrets.token_hex(16)
        approval = dict(actor=args.actor, report=args.report, action='create', target_path=target_path,
                        sha256=sha256(source), expires_at=time.time() + 900)
        (service.root / 'approvals' / (approval_id + '.json')).write_text(json.dumps(approval), encoding='utf-8')
        print('Create approval valid for 15 minutes: ' + approval_id)
    elif args.command == 'enroll':
        import uuid
        report_id = str(uuid.UUID(args.report_id))
        service.backend.call('get', report_id=report_id)
        config['reports'][identifier(args.alias)] = report_id
        if args.alias not in config['clients']['local-operator']['reports']:
            config['clients']['local-operator']['reports'].append(args.alias)
        path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        print('Report enrolled. Restart the service to apply.')
    elif args.command == 'approve':
        service.authorize(args.actor, args.report, 'publish')
        source = Path(args.file).resolve()
        permitted_root = service.release if args.action == 'publish' else service.root / 'backups'
        if not source.is_relative_to(permitted_root) or source.suffix.lower() != '.pbix':
            raise SystemExit('Approval file must be inside release_root or backup directory')
        import re
        if not re.fullmatch('[0-9a-f]{64}', args.expected_current_sha256):
            raise SystemExit('Expected SHA256 must contain 64 lowercase hex digits')
        approval_id = secrets.token_hex(16)
        approval = dict(actor=args.actor, report=args.report, action=args.action,
                        sha256=sha256(source), expected_current_sha256=args.expected_current_sha256,
                        expires_at=time.time() + 900)
        (service.root / 'approvals' / (approval_id + '.json')).write_text(json.dumps(approval), encoding='utf-8')
        print('Approval valid for 15 minutes: ' + approval_id)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, PermissionError) as exc:
        raise SystemExit(str(exc)) from None
