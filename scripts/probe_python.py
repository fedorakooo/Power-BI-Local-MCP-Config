"""Standard-library runtime inventory; optional checks of installed Windows dependencies."""
import json
import platform
import struct
import sys
from pathlib import Path

if '--check-dependencies' in sys.argv:
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/powerbi-reportserver-mcp'))
    for name in ('mcp', 'uvicorn', 'PIL', 'pywinauto', 'comtypes', 'win32api', 'cryptography',
                 'pbirs_mcp.server', 'pbirs_mcp.windows_worker', 'pbirs_mcp.report_authoring'):
        importlib.import_module(name)
    print('Python dependency imports verified')
else:
    print(json.dumps(dict(executable=sys.executable,
        base_executable=getattr(sys, '_base_executable', sys.executable),
        major=sys.version_info.major, minor=sys.version_info.minor,
        releaselevel=sys.version_info.releaselevel, bits=struct.calcsize('P') * 8,
        implementation=platform.python_implementation(), platform=sys.platform,
        version=platform.python_version())))
