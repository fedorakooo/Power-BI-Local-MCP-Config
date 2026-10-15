"""Supervise four pinned Supergateway backends and an IP-restricted Caddy frontend."""
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / 'runtime').mkdir(exist_ok=True)
entry = root / 'gateway/node_modules/supergateway/dist/index.js'
children = []
logs = []
names = {}


def record(event, **details):
    with (root/'runtime/supervisor.log').open('a', encoding='utf-8') as output:
        output.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(), event=event, **details)) + '\n')

def start(args, name, env=None):
    log = (root / 'runtime' / (name + '.log')).open('ab', buffering=0)
    logs.append(log)
    child = subprocess.Popen(args, cwd=root, env=env, stdin=subprocess.PIPE, stdout=log, stderr=log,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    children.append(child)
    names[child.pid] = name
    record('child_started', name=name, pid=child.pid)
    return child

try:
    record('supervisor_started', pid=os.getpid(), python=sys.executable)
    paths = json.loads((root / 'runtime/gateway-paths.json').read_text(encoding='utf-8-sig'))
    config = json.loads((root / 'gateway/servers.local.json').read_text(encoding='utf-8-sig'))
    node = paths['node']
    for i, (name, server) in enumerate(config['mcpServers'].items()):
        command = subprocess.list2cmdline([server['command'], *server['args']])
        env = dict(os.environ, **server.get('env', {}))
        start([node, str(entry), '--stdio', command, '--outputTransport', 'streamableHttp', '--stateful',
               '--sessionTimeout', '900000', '--port', str(server.get('port', 8013 + i)), '--healthEndpoint', '/healthz'], name, env)
    env = dict(os.environ)
    start([str(root / 'runtime/bin/caddy.exe'), 'run', '--config', str(root / 'gateway/Caddyfile'), '--adapter', 'caddyfile'], 'caddy', env)
    (root / 'runtime/gateway-processes.json').write_text(json.dumps({'supervisor': os.getpid(), 'children': [p.pid for p in children]}))
    while all(p.poll() is None for p in children):
        time.sleep(1)
    for child in children:
        if child.poll() is not None:
            record('child_exited', name=names[child.pid], pid=child.pid, exit_code=child.returncode)
    sys.exit(1)
except BaseException:
    with (root/'runtime/supervisor.log').open('a', encoding='utf-8') as output:
        traceback.print_exc(file=output)
    raise
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for log in logs:
        log.close()
