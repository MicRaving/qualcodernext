"""Actively start LM Studio and load the configured model.

LM Studio ships an ``lms`` CLI that can start its local server
(``lms server start``) and load a model into memory (``lms load <key>``).
When QCnext's AI feature targets the ``lmstudio`` provider and finds nothing
listening on the configured port, this service launches both — so an AI chat
works without the user manually opening the LM Studio app first.

Design notes:
- All functions are synchronous; callers wrap them in ``asyncio.to_thread``
  (the CLI calls block for seconds, model loads potentially for minutes).
- Reachability is probed over HTTP against the OpenAI-compatible API rather
  than parsed from CLI output, so the check exercises exactly what the AI
  client will use.
- The CLI is discovered via the ``QC_LMS_CLI`` env override, then ``PATH``,
  then the standard per-user install location used by LM Studio's bundled
  bootstrap (``~/.lmstudio/bin/lms.exe`` on Windows).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

#: How long to wait for the server to accept connections after start.
SERVER_START_TIMEOUT_S = 30.0
#: How long a single ``lms`` invocation may run. Loading a large model into
#: RAM/VRAM can take minutes, hence the generous cap.
LOAD_TIMEOUT_S = 600.0


def _standard_candidates() -> list[Path]:
    home = Path.home()
    binary = "lms.exe" if os.name == "nt" else "lms"
    return [
        home / ".lmstudio" / "bin" / binary,
        Path.home() / ".cache" / "lm-studio" / "bin" / binary,
    ]


def find_lms() -> str | None:
    """Locate the LM Studio ``lms`` CLI, or None when it is not installed."""
    override = os.environ.get("QC_LMS_CLI", "").strip()
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("lms")
    if found:
        return found
    for candidate in _standard_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def _run_lms(cli: str, args: list[str], timeout_s: float) -> tuple[bool, str]:
    """Run one lms command; ``(success, combined output)``.

    CREATE_NO_WINDOW keeps the packaged Windows app from flashing a console
    (same convention as r_service).
    """
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [cli, *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            creationflags=creationflags,
        )
    except Exception as err:
        return False, str(err)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, output


def reachable(api_base: str) -> bool:
    """True when something answers ``GET {api_base}/models`` right now."""
    if not api_base:
        return False
    url = f"{api_base.rstrip('/')}/models"
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(url)
        return response.status_code < 500
    except Exception:
        return False


def loaded_ids(api_base: str) -> list[str]:
    """Model ids currently served by the backend ([] when unreachable)."""
    if not api_base:
        return []
    url = f"{api_base.rstrip('/')}/models"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
        data = response.json()
    except Exception:
        return []
    ids: list[str] = []
    for item in data.get("data") or []:
        mid = str(item.get("id") or "").strip()
        if mid:
            ids.append(mid)
    return ids


def _model_is_loaded(api_base: str, model: str) -> bool:
    """Tolerant match: exact id first, then case-insensitive containment."""
    ids = loaded_ids(api_base)
    if not model:
        return True
    lowered = model.lower()
    return any(mid == model or lowered in mid.lower() or mid.lower() in lowered for mid in ids)


def ensure_lmstudio(
    api_base: str,
    model: str,
    server_start_timeout_s: float = SERVER_START_TIMEOUT_S,
    load_timeout_s: float = LOAD_TIMEOUT_S,
) -> dict:
    """Make sure the LM Studio server is up and ``model`` is loaded.

    Returns ``{ok, started_server, loaded_model, already_ready, error}``.
    Idempotent: every step is skipped when its goal is already met.
    """
    api_base = (api_base or "").strip()
    model = (model or "").strip()

    def _result(ok: bool, *, started_server: bool = False, loaded_model: bool = False,
                already_ready: bool = False, error: str = "") -> dict:
        return {
            "ok": ok,
            "started_server": started_server,
            "loaded_model": loaded_model,
            "already_ready": already_ready,
            "error": error,
        }

    if not api_base:
        return _result(False, error="no api_base configured")

    # Fast path: everything already in place.
    if reachable(api_base) and _model_is_loaded(api_base, model):
        return _result(True, already_ready=True)

    cli = find_lms()
    if cli is None:
        return _result(
            False,
            error=(
                "LM Studio CLI not found (looked in PATH and ~/.lmstudio/bin). "
                "Install LM Studio or set QC_LMS_CLI."
            ),
        )

    started_server = False
    if not reachable(api_base):
        ok, output = _run_lms(cli, ["server", "start"], timeout_s=60)
        if not ok:
            return _result(False, started_server=False, error=f"lms server start failed: {output}")
        started_server = True
        deadline = time.monotonic() + server_start_timeout_s
        while time.monotonic() < deadline:
            if reachable(api_base):
                break
            time.sleep(0.5)
        if not reachable(api_base):
            return _result(
                False,
                started_server=True,
                error="LM Studio server did not come up within the timeout",
            )

    loaded_model = False
    if model and not _model_is_loaded(api_base, model):
        ok, output = _run_lms(cli, ["load", model], timeout_s=load_timeout_s)
        if not ok:
            return _result(
                False,
                started_server=started_server,
                error=f"lms load failed: {output}",
            )
        # The HTTP model list can lag slightly behind the CLI returning.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not _model_is_loaded(api_base, model):
            time.sleep(0.5)
        loaded_model = _model_is_loaded(api_base, model)

    return _result(True, started_server=started_server, loaded_model=loaded_model)
