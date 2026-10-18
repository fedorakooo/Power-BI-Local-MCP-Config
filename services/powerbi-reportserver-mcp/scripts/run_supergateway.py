"""Supervise four pinned Supergateway backends and an IP-restricted Caddy frontend."""
import json
import os
import subprocess
import sys
import time
import traceback
import argparse
import logging
import logging.handlers
import threading
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / 'runtime').mkdir(exist_ok=True)
entry = root / 'gateway/node_modules/supergateway/dist/index.js'
children = []
logs = []
readers = []
names = {}
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['combined', 'background', 'desktop'], default='combined')
mode = parser.parse_args().mode


def record(event, **details):
    with (root/'runtime/supervisor.log').open('a', encoding='utf-8') as output:
        output.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(), event=event, **details)) + '\n')

def start(args, name, env=None):
    log = logging.handlers.RotatingFileHandler(root/'runtime'/(name+'.log'),
        maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    log.setFormatter(logging.Formatter('%(message)s'))
    logs.append(log)
    record('child_starting', name=name, executable=str(args[0]))
    try:
        child = subprocess.Popen(args, cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as error:
        record('child_start_failed', name=name, executable=str(args[0]),
               winerror=getattr(error, 'winerror', None), error=str(error))
        raise
    children.append(child)
    names[child.pid] = name
    def drain():
        try:
            for line in iter(child.stdout.readline, b''):
                log.emit(logging.LogRecord(name, logging.INFO, '', 0,
                    line.decode('utf-8', errors='replace').rstrip('\r\n'), (), None))
        finally:
            child.stdout.close()
    reader = threading.Thread(target=drain, name='log-'+name, daemon=True)
    reader.start()
    readers.append(reader)
    record('child_started', name=name, pid=child.pid)
    return child

try:
    record('supervisor_started', pid=os.getpid(), python=sys.executable)
    paths = json.loads((root / 'runtime/gateway-paths.json').read_text(encoding='utf-8-sig'))
    config = json.loads((root / 'gateway/servers.local.json').read_text(encoding='utf-8-sig'))
    node = paths['node']
    for i, (name, server) in enumerate(config['mcpServers'].items()):
        is_desktop = name == 'stair-powerbi-desktop'
        if (mode == 'background' and is_desktop) or (mode == 'desktop' and not is_desktop):
            continue
        command = subprocess.list2cmdline([server['command'], *server['args']])
        env = dict(os.environ, **server.get('env', {}))
        start([node, str(entry), '--stdio', command, '--outputTransport', 'streamableHttp', '--stateful',
               '--sessionTimeout', '900000', '--port', str(server.get('port', 8013 + i)), '--healthEndpoint', '/healthz'], name, env)
    env = dict(os.environ)
    if mode != 'desktop' and (root / 'runtime/headless-supervisor.json').is_file():
        start([sys.executable, str(root / 'scripts/supervise_headless.py')], 'stair-powerbi-headless', env)
    if mode != 'desktop':
        start([sys.executable, str(root / 'scripts/supervise_caddy.py')], 'caddy', env)
    process_file = 'desktop-processes.json' if mode == 'desktop' else 'gateway-processes.json'
    (root / 'runtime' / process_file).write_text(json.dumps({'supervisor': os.getpid(), 'children': [p.pid for p in children]}))
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
    # EOF gives Supergateway and the Caddy guard a chance to stop their own children.
    for child in children:
        if child.stdin:
            child.stdin.close()
    for child in children:
        if child.poll() is None:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)
    for reader in readers:
        reader.join(timeout=5)
    for log in logs:
        log.close()
