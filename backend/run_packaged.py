"""Packaged-app entry point — starts the FastAPI server programmatically.

Port selection: binds 8765; when that is taken (a second app instance, or a
dev backend) an ephemeral free port is used instead. The chosen port is
written to ``%TEMP%\\qualcoder-port-<pid>.json`` so the Tauri shell can
discover it (multiple app instances each get their own backend + port).
"""

import json
import os
import socket
import sys
import tempfile

import uvicorn

from qualcoder_api.main import app

DEFAULT_PORT = 8765


def pick_port() -> int:
    """Return the default port when free, else an ephemeral free port."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", DEFAULT_PORT))
        probe.close()
        return DEFAULT_PORT
    except OSError:
        pass
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


if __name__ == "__main__":
    port = pick_port()
    pid = os.getpid()
    port_file = os.path.join(tempfile.gettempdir(), f"qualcoder-port-{pid}.json")
    try:
        with open(port_file, "w", encoding="utf-8") as f:
            json.dump({"port": port, "pid": pid}, f)
    except OSError:
        port_file = ""
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    finally:
        if port_file:
            try:
                os.remove(port_file)
            except OSError:
                pass
