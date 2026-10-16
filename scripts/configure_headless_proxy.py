"""Expose the loopback headless MCP inside the existing IP-restricted Caddy handle."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

BEGIN = '        # BEGIN FEDARAKA HEADLESS MCP\n'
END = '        # END FEDARAKA HEADLESS MCP\n'


def with_route(text, port):
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('Invalid headless backend port')
    if '    @allowed remote_ip ' not in text or text.count('    handle @allowed {\n') != 1:
        raise ValueError('Expected the existing IP-restricted Caddy frontend')
    if (BEGIN in text) != (END in text) or text.count(BEGIN) > 1 or text.count(END) > 1:
        raise ValueError('Invalid managed headless route markers')
    text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END), '', text, flags=re.S)
    if '/fedaraka-powerbi-headless/' in text:
        raise ValueError('Unmanaged headless route exists; review it before changing configuration')
    block = BEGIN + (
        f'        handle_path /fedaraka-powerbi-headless/* {{\n'
        f'            reverse_proxy 127.0.0.1:{port} {{\n'
        f'                header_up Host 127.0.0.1:{port}\n'
        f'                flush_interval -1\n'
        f'            }}\n'
        f'        }}\n') + END
    return text.replace('    handle @allowed {\n', '    handle @allowed {\n' + block, 1)


def configure(root, config, port):
    root = Path(root).resolve()
    settings = json.loads(Path(config).read_text(encoding='utf-8-sig'))
    if port in range(settings['frontend_port'], settings['frontend_port'] + 5):
        raise ValueError('Headless backend overlaps the existing gateway ports')
    service = root / 'services/powerbi-reportserver-mcp'
    path = service / 'gateway/Caddyfile'
    before = path.read_text(encoding='utf-8-sig')
    after = with_route(before, port)
    changed = before != after
    if changed:
        pending = path.with_name('Caddyfile.headless.pending')
        try:
            pending.write_text(after, encoding='utf-8')
            result = subprocess.run([str(service / 'runtime/bin/caddy.exe'), 'validate',
                '--config', str(pending), '--adapter', 'caddyfile'], capture_output=True,
                text=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise RuntimeError('Caddy rejected the generated headless route; existing configuration preserved')
            # Keep the previous configuration for local diagnosis.
            path.with_name('Caddyfile.before-headless').write_text(before, encoding='utf-8')
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
    generated = root / 'generated'
    generated.mkdir(exist_ok=True)
    url = f'http://127.0.0.1:{settings["frontend_port"]}/fedaraka-powerbi-headless/mcp'
    (generated / 'headless-proxy-mcp.toml').write_text(
        '[mcp_servers.fedaraka-powerbi-headless]\nurl = ' + json.dumps(url) + '\n', encoding='utf-8')
    return {'status': 'headless_proxy_configured', 'changed': changed, 'url': url, 'backend_port': port}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    print(json.dumps(configure(args.root, args.config, args.port)))
