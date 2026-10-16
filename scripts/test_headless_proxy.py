import unittest
from configure_headless_proxy import with_route

CONFIG = '''{
    admin off
}
:8012 {
    @allowed remote_ip 127.0.0.1 10.26.10.14
    handle @allowed {
        handle_path /fedaraka-powerbi-modeling/* {
            reverse_proxy 127.0.0.1:8013
        }
    }
    respond "Forbidden" 403
}
'''


class ProxyTests(unittest.TestCase):
    def test_route_stays_inside_existing_allowlist(self):
        value = with_route(CONFIG, 8020)
        self.assertLess(value.index('handle @allowed'), value.index('/fedaraka-powerbi-headless/'))
        self.assertIn('header_up Host 127.0.0.1:8020', value)
        self.assertIn('@allowed remote_ip 127.0.0.1 10.26.10.14', value)
        self.assertIn('respond "Forbidden" 403', value)

    def test_repeated_configuration_is_idempotent_and_port_can_change(self):
        value = with_route(CONFIG, 8020)
        self.assertEqual(value, with_route(value, 8020))
        changed = with_route(value, 8021)
        self.assertEqual(changed.count('handle_path /fedaraka-powerbi-headless/'), 1)
        self.assertNotIn(':8020', changed)

    def test_unrestricted_or_unmanaged_configuration_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'IP-restricted'):
            with_route(':8012 { reverse_proxy 127.0.0.1:8020 }', 8020)
        with self.assertRaisesRegex(ValueError, 'Unmanaged'):
            with_route(CONFIG.replace('handle_path /fedaraka-powerbi-modeling/',
                                     'handle_path /fedaraka-powerbi-headless/'), 8020)


if __name__ == '__main__':
    unittest.main()
