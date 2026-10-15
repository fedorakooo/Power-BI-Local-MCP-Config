import hashlib
import unittest
from types import SimpleNamespace

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from pbirs_mcp.server import Authentication, actor_var
from pbirs_mcp.observability import TraceContextMiddleware


class AuthTests(unittest.TestCase):
    def setUp(self):
        async def inner(scope, receive, send):
            await JSONResponse({'actor': actor_var.get()})(scope, receive, send)
        service = SimpleNamespace(config={'clients': {'alice': {
            'token_sha256': hashlib.sha256(b'test-only-token').hexdigest()}}})
        self.client = TestClient(TraceContextMiddleware(Authentication(inner, service)))

    def test_anonymous_and_spoofed_identity_denied(self):
        self.assertEqual(self.client.post('/mcp', headers={'X-User-Id': 'alice'}).status_code, 401)
        self.assertEqual(self.client.post('/mcp', headers={'Authorization': 'Bearer wrong'}).status_code, 401)

    def test_valid_token_maps_to_server_side_identity(self):
        response = self.client.post('/mcp', headers={'Authorization': 'Bearer test-only-token', 'X-User-Id': 'someone-else'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['actor'], 'alice')
        self.assertEqual(actor_var.get(), '')

    def test_trace_context_echoed_even_on_auth_failure(self):
        trace = 'a' * 32
        response = self.client.post('/mcp', headers={'traceparent': '00-' + trace + '-' + 'b' * 16 + '-01'})
        self.assertEqual(response.headers['X-Trace-ID'], trace)


if __name__ == '__main__':
    unittest.main()
