"""One-shot: launch uvicorn like e2e, POST /projects, check settings."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import urllib.request

SETTINGS = Path.home() / ".qualcoder" / "settings.json"
if SETTINGS.exists():
    SETTINGS.unlink()
print("pre: settings exists =", SETTINGS.exists())

proc = subprocess.Popen(
    [
        r".venv\Scripts\python.exe", "-m", "uvicorn",
        "qualcoder_api.main:app", "--port", "8799",
    ],
    cwd=r"D:\Downloads\qualcoder-rework\backend",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
try:
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8799/api/v1/health", timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.5)

    req = urllib.request.Request(
        "http://127.0.0.1:8799/api/v1/projects",
        data=json.dumps({"project_path": r"C:\Users\marvi\AppData\Local\Temp\qc-probe\Probe.qda",
                         "codername": "probe"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("POST /projects:", r.status, r.read().decode()[:120])

    print("post: settings exists =", SETTINGS.exists())
finally:
    proc.kill()
