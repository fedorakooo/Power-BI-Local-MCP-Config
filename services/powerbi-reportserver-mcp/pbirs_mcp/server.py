from __future__ import annotations

import argparse
import contextvars
import hashlib
import hmac
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .core import Service
from .observability import TraceContextMiddleware, configure_contract_logging
from .otel_tracing import OtelSpanHooks, setup_tracing, shutdown_tracing

actor_var = contextvars.ContextVar('pbirs_actor', default='')


class Authentication:
    def __init__(self, app, service):
        self.app, self.service = app, service

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if scope['path'] == '/health' and scope['method'] == 'GET':
            return await JSONResponse({'status': 'running', 'write_enabled': self.service.config.get('write_enabled', False)})(scope, receive, send)
        headers = dict(scope.get('headers', []))
        auth = headers.get(b'authorization', b'').decode('latin1')
        actor = ''
        if auth.startswith('Bearer '):
            digest = hashlib.sha256(auth[7:].encode()).hexdigest()
            for name, client in self.service.config.get('clients', {}).items():
                expected = client.get('token_sha256', '')
                if expected and hmac.compare_digest(digest, expected):
                    actor = name
                    break
        if not actor:
            logging.getLogger(__name__).warning('mcp_auth_denied')
            return await JSONResponse({'error': 'Unauthorized'}, status_code=401)(scope, receive, send)
        token = actor_var.set(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            actor_var.reset(token)


def build_mcp(service):
    @asynccontextmanager
    async def lifespan(_):
        try:
            yield
        finally:
            shutdown_tracing()

    mcp = FastMCP('Power BI Report Server', stateless_http=True, json_response=True,
                 lifespan=lifespan,
                 transport_security=TransportSecuritySettings(
                     enable_dns_rebinding_protection=True,
                     allowed_hosts=service.config.get('mcp_allowed_hosts', ['127.0.0.1:*', 'localhost:*', '[::1]:*']),
                     allowed_origins=service.config.get('mcp_allowed_origins', ['http://127.0.0.1:*', 'http://localhost:*'])))

    @mcp.tool(annotations={'readOnlyHint': True})
    def list_reports() -> list[dict]:
        """List only Report Server reports authorized for this caller."""
        return service.list_reports(actor_var.get())

    @mcp.tool(annotations={'readOnlyHint': True})
    def get_report_link(report: str) -> dict:
        """Return catalog-derived authenticated report and iframe URLs for an authorized alias."""
        return service.get_report_link(actor_var.get(), report)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False})
    def download_report_backup(report: str) -> dict:
        """Store a private server-side PBIX backup; return its ID and SHA256, never raw contents."""
        return service.download_report_backup(actor_var.get(), report)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False})
    def publish_reviewed_pbix(report: str, file_name: str, approval_id: str | None = None,
                              expected_sha256: str | None = None, expected_current_sha256: str | None = None) -> dict:
        """Publish a PBIX from release_root. First get_publication_policy. In automatic mode omit approval_id
        and supply exact built expected_sha256 plus fresh backup expected_current_sha256; no human CLI needed.
        Other targets require an operator-issued one-use approval. Automatically back up before updating.
        Never retry a failed or uncertain publication; inspect the report and obtain a new approval.
        This tool neither edits Desktop visuals nor saves an open Desktop file.
        """
        return service.publish_reviewed_pbix(actor_var.get(), report, file_name, approval_id, expected_sha256, expected_current_sha256)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False})
    def publish_new_reviewed_pbix(destination: str, file_name: str, approval_id: str | None = None, expected_sha256: str | None = None) -> dict:
        """Create a NEW catalog report at an enrolled destination. Check get_publication_policy first.
        In automatic mode omit approval_id and supply exact built expected_sha256; no human CLI needed.
        Otherwise requires an operator create approval. Never overwrites an existing item. Verify download
        hash; rendering is separate. Uncertain automatic writes block further automatic publication until inspected."""
        return service.publish_new_reviewed_pbix(actor_var.get(), destination, file_name, approval_id, expected_sha256)

    @mcp.tool(annotations={'readOnlyHint': True})
    def get_publication_policy(report: str) -> dict:
        """Read this actor's publication mode for an enrolled report/destination: automatic or operator_approval.
        Automatic create/update needs exact artifact hash; update also needs the fresh server backup hash.
        This tool reads policy and cannot change it."""
        return service.get_publication_policy(actor_var.get(), report)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False})
    def restore_previous_pbix(report: str, backup_id: str, approval_id: str) -> dict:
        """Restore an authorized backup; requires a fresh operator-issued restore approval."""
        return service.restore_previous_pbix(actor_var.get(), report, backup_id, approval_id)

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=os.getenv('PBIRS_CONFIG', 'config.local.json'))
    parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8010)
    parser.add_argument('--ssl-certfile')
    parser.add_argument('--ssl-keyfile')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    configure_contract_logging('powerbi-reportserver-mcp', stream=sys.stderr if args.transport == 'stdio' else sys.stdout)
    setup_tracing('powerbi-reportserver-mcp', scope='pbirs_mcp')
    service = Service(config)
    mcp = build_mcp(service)
    if args.transport == 'stdio':
        actor = os.getenv('PBIRS_STDIO_ACTOR', '')
        if actor not in config.get('clients', {}):
            raise ValueError('Set PBIRS_STDIO_ACTOR to a configured local principal')
        actor_var.set(actor)
        mcp.run(transport='stdio')
    else:
        if args.host not in ('127.0.0.1', 'localhost', '::1') and not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError('Non-loopback listener requires a TLS certificate and key')
        app = TraceContextMiddleware(Authentication(mcp.streamable_http_app(), service), span_hooks=OtelSpanHooks())
        uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=args.ssl_certfile,
                    ssl_keyfile=args.ssl_keyfile, access_log=False, log_config=None)


if __name__ == '__main__':
    main()
