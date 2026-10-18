"""Run the enrolled HTTP MCP under the scheduled gateway's parent-pipe guard."""
import json
import os
import sys
from pathlib import Path
from supervise_caddy import supervise

service = Path(__file__).resolve().parents[1]
root = service.parents[1]
settings = json.loads((service / 'runtime/headless-supervisor.json').read_text(encoding='utf-8-sig'))
port = settings['port']
if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
    raise ValueError('Invalid enrolled headless port')
os.environ['PYTHONPATH'] = str(service)
sys.exit(supervise([str(root / 'runtime/headless/.venv/Scripts/python.exe'),
    '-m', 'pbirs_mcp.headless_build', '--config', str(root / 'headless/config.local.json'),
    '--http-port', str(port)]))
