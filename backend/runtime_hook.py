"""PyInstaller runtime hook — log redirect + backend-source overlay.

Windowed (console=False) builds have no console streams; some libraries
(uvicorn logging, pydantic, etc.) break when sys.stdout/stderr are None.
The log lives in the user's TEMP dir.

Overlay: when ``~/.qualcoder/patches/current/`` holds a ``qualcoder_api``
package (installed by a signed nightly backend patch), it is prepended to
``sys.path`` so the loose sources shadow the frozen PYZ — the backend then
runs patched Python without touching the installed binaries. Proven by the
overlay micro-test (frozen ``sys.path`` entries win over the PYZ importer);
mirrored testably in ``qualcoder_api.services.overlay.overlay_dir``.
Deliberately dependency-free and bulletproof (try/except): a broken patch
must never prevent boot — worst case the overlay is skipped.
"""

import contextlib
import os
import sys

_log_path = os.path.join(os.environ.get("TEMP", "."), "qualcoder-backend.log")
try:
    # Kept open deliberately: it becomes sys.stdout/sys.stderr.
    _log = open(_log_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = _log
    sys.stderr = _log
except OSError:
    pass

try:
    _overlay = os.environ.get("QC_OVERLAY_DIR") or os.path.join(
        os.path.expanduser("~"), ".qualcoder", "patches", "current"
    )
    if os.path.isdir(os.path.join(_overlay, "qualcoder_api")) and _overlay not in sys.path:
        sys.path.insert(0, _overlay)
        print(f"[runtime-hook] backend overlay active: {_overlay}")
except Exception as _err:  # boot must never fail here
    with contextlib.suppress(Exception):
        print(f"[runtime-hook] overlay skipped: {_err}")
