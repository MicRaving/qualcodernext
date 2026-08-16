"""R integration — Rscript detection and the R run job engine.

``find_rscript`` probes PATH, ``R_HOME`` and the standard install dirs of
the three desktop platforms. R jobs are short-lived background processes:
each job writes its script to ``<project>/r_exchange/logs/<job_id>.R`` and
spawns ``Rscript --vanilla --encoding=UTF-8 <script.R>`` with
``QC_PORT``/``QC_PROJECT``/``QC_EXCHANGE`` in the environment (the R side
talks back to this backend over HTTP and reads/writes the exchange
directory). stdout/stderr are captured live into the job record (tail) and
onto disk (``<job_id>.out`` / ``<job_id>.err``); artifacts are any
``.png``/``.csv`` the run writes into ``r_exchange/out/``.

The job registry mirrors ``transcription`` (in-process dict + lock). R runs
are short and need no pause/resume, so the queue surface is just
queued/running/done/error plus cancel; progress is text (the live output
tail).
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from asyncio import create_subprocess_exec
from datetime import datetime
from pathlib import Path
from shutil import which

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765
TAIL_LINES = 50

# In-process job registry: job_id -> state dict. One backend serves one app
# instance, so an in-memory registry is sufficient.
_JOBS: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_ARTIFACT_MEDIA = {"png": "image/png", "csv": "text/plain"}
_R_VERSION_RE = re.compile(r"R-(\d+)\.(\d+)(?:\.(\d+))?")


# ----------------------------------------------------------------------
# Rscript detection
# ----------------------------------------------------------------------


def _standard_candidates() -> list[Path]:
    """Rscript locations of the standard installs, per platform."""
    if os.name == "nt":
        candidates = [Path(match) for match in glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe")]
        candidates.sort(key=_r_install_version, reverse=True)
        return candidates
    candidates = [Path("/usr/bin/Rscript"), Path("/usr/local/bin/Rscript")]
    if sys.platform == "darwin":
        candidates.append(Path("/Library/Frameworks/R.framework/Resources/bin/Rscript"))
    return candidates


def _r_install_version(path: Path) -> tuple[int, int, int]:
    """Sort key for ``R-<m>.<minor>[.<patch>]`` install dirs (newest first)."""
    match = _R_VERSION_RE.search(str(path))
    if match is None:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def find_rscript() -> str | None:
    """Locate an ``Rscript`` executable, or None when R is not installed."""
    found = which("Rscript")
    if found:
        return found
    r_home = os.environ.get("R_HOME")
    if r_home:
        candidate = Path(r_home) / "bin" / ("Rscript.exe" if os.name == "nt" else "Rscript")
        if candidate.is_file():
            return str(candidate)
    for candidate in _standard_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def r_version(path: str) -> str | None:
    """Ask Rscript for its version (first line, e.g. ``4.3.1``)."""
    try:
        # CREATE_NO_WINDOW: never flash a console window for the probe
        # (the packaged app has no console; a visible popup would be a bug).
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10,
            creationflags=creationflags,
        )
    except Exception:
        return None
    first = (result.stdout or result.stderr or "").strip().splitlines()
    if not first:
        return None
    match = re.search(r"\d+\.\d+(?:\.\d+)?", first[0])
    return match.group(0) if match else first[0]


def get_status() -> dict:
    """``{available, path, version}`` for the machine's R install."""
    path = find_rscript()
    return {
        "available": path is not None,
        "path": path,
        "version": r_version(path) if path else None,
    }


# ----------------------------------------------------------------------
# Port discovery (the packaged shell writes %TEMP%\\qualcoder-port-<pid>.json)
# ----------------------------------------------------------------------


def _port_files() -> list[str]:
    return glob.glob(os.path.join(tempfile.gettempdir(), "qualcoder-port-*.json"))


def get_current_port() -> int:
    """Port of the newest live backend (from its port file), else the default."""
    files = _port_files()
    if not files:
        return DEFAULT_PORT
    try:
        newest = max(files, key=os.path.getmtime)
        with open(newest, encoding="utf-8") as f:
            return int(json.load(f)["port"])
    except Exception:
        return DEFAULT_PORT


# ----------------------------------------------------------------------
# Exchange directory
# ----------------------------------------------------------------------


def get_exchange_dir(project_path: str) -> Path:
    """``<project>/r_exchange`` with ``in/``, ``out/``, ``logs/`` subdirs."""
    exchange = Path(project_path) / "r_exchange"
    for sub in ("in", "out", "logs"):
        (exchange / sub).mkdir(parents=True, exist_ok=True)
    return exchange


# ----------------------------------------------------------------------
# Job registry (mirrors transcription's registry)
# ----------------------------------------------------------------------


def get_r_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        # Strip the private control fields — they must never be JSON-serialized.
        return {k: v for k, v in job.items() if not k.startswith("_")} if job else None


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)


def _is_cancelled(job_id: str) -> bool:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        return bool(job and job.get("_cancelled") and job["_cancelled"].is_set())


def start_r_job(*, project_path: str, script: str, rscript: str | None = None) -> str:
    """Queue an R run and return its id (executes as an asyncio task).

    The script is persisted to ``r_exchange/logs/<job_id>.R`` first, so a
    crash mid-run still leaves the submitted script on disk.
    """
    job_id = uuid.uuid4().hex[:12]
    rscript = rscript or find_rscript()
    exchange = get_exchange_dir(project_path)
    (exchange / "logs" / f"{job_id}.R").write_text(script, encoding="utf-8")
    now = time.time()
    with _jobs_lock:
        _JOBS[job_id] = {
            "id": job_id,
            "state": "queued",
            "message": "queued",
            "progress": 0.0,
            "stdout_tail": "",
            "stderr_tail": "",
            "exit_code": None,
            "returncode": None,
            "error": None,
            "outputs": [],
            "script_name": f"{job_id}.R",
            "project_path": project_path,
            "created": now,
            "started": now,
            "finished": None,
            "_rscript": rscript,
            "_cancelled": threading.Event(),
            "_proc": None,
        }
    asyncio.get_running_loop().create_task(_run_r_job(job_id, project_path, rscript))
    return job_id


def control_r_job(job_id: str, action: str) -> bool:
    """Cancel a queued/running job (terminating its Rscript process)."""
    if action != "cancel":
        return False
    proc = None
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None or job.get("state") not in ("queued", "running"):
            return False
        job["state"] = "cancelled"
        job["message"] = "cancelled"
        job["_cancelled"].set()
        proc = job.get("_proc")
    if proc is not None and proc.returncode is None:
        proc.terminate()
    return True


# ----------------------------------------------------------------------
# Job worker
# ----------------------------------------------------------------------


async def _run_r_job(job_id: str, project_path: str, rscript: str | None) -> None:
    exchange = get_exchange_dir(project_path)
    logs = exchange / "logs"
    out_dir = exchange / "out"
    script_path = logs / f"{job_id}.R"
    if rscript is None:
        _set_job(job_id, state="error", message="R not found", error="Rscript was not found on this machine")
        return
    if _is_cancelled(job_id):
        return
    env = os.environ.copy()
    env["QC_PORT"] = str(get_current_port())
    env["QC_PROJECT"] = project_path
    env["QC_EXCHANGE"] = str(exchange)
    _set_job(job_id, state="running", message="starting Rscript", progress=0.0)
    try:
        proc = await create_subprocess_exec(
            rscript,
            "--vanilla",
            "--encoding=UTF-8",
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(out_dir),
            env=env,
            # Never flash a console window for R jobs in the packaged app.
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as err:
        _set_job(job_id, state="error", message="failed to start Rscript", error=str(err))
        return
    if _is_cancelled(job_id):
        with contextlib.suppress(Exception):
            proc.terminate()
            await proc.wait()
        return
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is not None:
            job["_proc"] = proc
    await asyncio.gather(
        _pump(job_id, proc.stdout, "stdout_tail", logs / f"{job_id}.out"),
        _pump(job_id, proc.stderr, "stderr_tail", logs / f"{job_id}.err"),
    )
    if _is_cancelled(job_id):
        with contextlib.suppress(Exception):
            await proc.wait()
        return
    code = await proc.wait()
    with _jobs_lock:
        started = float((_JOBS.get(job_id) or {}).get("started", 0.0))
        stderr_tail = str((_JOBS.get(job_id) or {}).get("stderr_tail", ""))
    outputs = _scan_outputs(out_dir, started)
    finished = time.time()
    if code == 0:
        _set_job(
            job_id,
            state="done",
            message="done",
            progress=100.0,
            exit_code=code,
            returncode=code,
            outputs=outputs,
            finished=finished,
        )
    else:
        _set_job(
            job_id,
            state="error",
            message=f"R exited with code {code}",
            error=stderr_tail or f"R exited with code {code}",
            exit_code=code,
            returncode=code,
            outputs=outputs,
            finished=finished,
        )


async def _pump(job_id: str, stream, tail_key: str, file_path: Path) -> None:
    """Stream one pipe into the job record (tail) and its log file."""
    tail: list[str] = []
    try:
        with open(file_path, "w", encoding="utf-8", newline="\n") as fh:  # noqa: ASYNC230 - small local writes
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                fh.write(line + "\n")
                fh.flush()
                tail.append(line)
                del tail[:-TAIL_LINES]
                update: dict[str, str] = {tail_key: "\n".join(tail)}
                if line.strip():
                    update["message"] = line
                _set_job(job_id, **update)
    except Exception:
        logger.exception("R output pump failed for job %s", job_id)


def _scan_outputs(out_dir: Path, started: float) -> list[dict]:
    """Artifacts (``.png``/``.csv``) this run wrote into ``out/``."""
    if not out_dir.is_dir():
        return []
    outputs: list[dict] = []
    for path in sorted(out_dir.iterdir()):
        if not path.is_file():
            continue
        kind = path.suffix.lower().lstrip(".")
        if kind not in ("png", "csv"):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime < started:
            continue
        outputs.append({"name": path.name, "kind": kind, "size": st.st_size})
    return outputs


# ----------------------------------------------------------------------
# Artifacts (files an R run produced in r_exchange/out/)
# ----------------------------------------------------------------------


def list_artifacts(project_path: str) -> list[dict]:
    out_dir = Path(project_path) / "r_exchange" / "out"
    if not out_dir.is_dir():
        return []
    files: list[dict] = []
    for path in sorted(out_dir.iterdir()):
        if not path.is_file():
            continue
        kind = path.suffix.lower().lstrip(".")
        if kind not in ("png", "csv"):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        files.append(
            {
                "name": path.name,
                "kind": kind,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return files


def read_artifact(project_path: str, name: str) -> tuple[bytes, str] | None:
    """``(bytes, media_type)`` for one artifact, or None (missing/traversal).

    The name is sanitized: separators and ``..`` are rejected, so a request
    can never escape ``r_exchange/out/``.
    """
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    kind = Path(name).suffix.lower().lstrip(".")
    media_type = _ARTIFACT_MEDIA.get(kind)
    if media_type is None:
        return None
    path = Path(project_path) / "r_exchange" / "out" / name
    if not path.is_file():
        return None
    try:
        return path.read_bytes(), media_type
    except OSError:
        return None
