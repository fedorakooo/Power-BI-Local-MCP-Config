"""Stop Caddy when its supervising parent's stdin pipe closes."""
import json
import subprocess
import sys
import threading
from pathlib import Path


def supervise(command):
    parent_closed = threading.Event()

    def watch_parent():
        try:
            while sys.stdin.buffer.read(1):
                pass
        finally:
            parent_closed.set()

    threading.Thread(target=watch_parent, daemon=True).start()
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, close_fds=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print(json.dumps({'event': 'caddy_guard_started', 'child_pid': child.pid}), flush=True)
    try:
        while not parent_closed.wait(0.25):
            if child.poll() is not None:
                return child.returncode or 1
        print(json.dumps({'event': 'caddy_parent_pipe_closed'}), flush=True)
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.exit(supervise([str(root / 'runtime/bin/caddy.exe'), 'run', '--config',
                        str(root / 'gateway/Caddyfile'), '--adapter', 'caddyfile']))
