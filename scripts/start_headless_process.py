"""Detach the local MCP with only its log handles; do not inherit shell pipes."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--port', required=True, type=int)
args = parser.parse_args()
root = Path(args.root).resolve()
service = root / 'services/powerbi-reportserver-mcp'
runtime = root / 'runtime/headless'
env = dict(os.environ, PYTHONPATH=str(service))
with (runtime / 'stdout.log').open('ab', buffering=0) as stdout, (runtime / 'stderr.log').open('ab', buffering=0) as stderr:
    child = subprocess.Popen([sys.executable, '-m', 'pbirs_mcp.headless_build',
        '--config', str(root / 'headless/config.local.json'), '--http-port', str(args.port)],
        cwd=service, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
print(child.pid)
