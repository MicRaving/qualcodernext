"""PyInstaller runtime hook — redirect stdout/stderr to a log file.

Windowed (console=False) builds have no console streams; some libraries
(uvicorn logging, pydantic, etc.) break when sys.stdout/stderr are None.
The log lives in the user's TEMP dir.
"""

import os
import sys

_log_path = os.path.join(os.environ.get("TEMP", "."), "qualcoder-backend.log")
try:
    _log = open(_log_path, "w", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log
except OSError:
    pass
