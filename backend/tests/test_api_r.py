"""R integration API tests — detection, job engine lifecycle, artifacts.

Rscript is never executed: ``r_service.create_subprocess_exec`` is patched
with a fake process (canned stdout/stderr, optional start gate, chosen exit
code) so the async job engine can be driven deterministically.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.r import router as r_router
from qualcoder_api.main import app
from qualcoder_api.services import r_service as r_service_module

app.include_router(r_router, prefix="/api/v1")

FAKE_SCRIPT = "C:/fake/Rscript.exe"


class FakeStream:
    """Awaitable line source; an optional gate blocks the first readline."""

    def __init__(self, lines: list[str], gate: asyncio.Event | None = None):
        self._lines = [line.encode("utf-8") for line in lines]
        self._gate = gate

    async def readline(self) -> bytes:
        if self._gate is not None:
            await self._gate.wait()
            self._gate = None
        if not self._lines:
            return b""
        return self._lines.pop(0)


class FakeProcess:
    def __init__(
        self,
        args: tuple,
        kwargs: dict,
        stdout_lines: list[str],
        stderr_lines: list[str],
        returncode: int = 0,
        gate: asyncio.Event | None = None,
    ):
        self.args = args
        self.kwargs = kwargs
        self.stdout = FakeStream(stdout_lines, gate)
        self.stderr = FakeStream(stderr_lines)
        self.returncode = None
        self._returncode = returncode
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = self._returncode
        return self.returncode


def patch_r(
    monkeypatch,
    *,
    returncode: int = 0,
    gate: asyncio.Event | None = None,
    spawned: list | None = None,
    spawned_event: asyncio.Event | None = None,
):
    """Point the service at a fake Rscript + fake subprocess spawn."""
    monkeypatch.setattr(r_service_module, "find_rscript", lambda: FAKE_SCRIPT)

    async def fake_spawn(*args, **kwargs):
        proc = FakeProcess(
            args,
            kwargs,
            stdout_lines=["[1] 42", "done"],
            stderr_lines=[],
            returncode=returncode,
            gate=gate,
        )
        if spawned is not None:
            spawned.append(proc)
        if spawned_event is not None:
            spawned_event.set()
        return proc

    monkeypatch.setattr(r_service_module, "create_subprocess_exec", fake_spawn)


def patch_port_file(monkeypatch, tmp_path) -> int:
    """A fake ``qualcoder-port-*.json`` so the env port is deterministic."""
    port = 9876
    port_file = tmp_path / "qualcoder-port-1.json"
    port_file.write_text(json.dumps({"port": port, "pid": 1}), encoding="utf-8")
    monkeypatch.setattr(r_service_module, "_port_files", lambda: [str(port_file)])
    return port


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "r.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def wait_for_job(client, job_id: str, states: set[str], seconds: float = 5.0) -> dict:
    deadline = time.monotonic() + seconds
    body: dict = {}
    while time.monotonic() < deadline:
        res = await client.get(f"/api/v1/r/jobs/{job_id}")
        assert res.status_code == 200, res.text
        body = res.json()
        if body["state"] in states:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {states}: {body}")


# ----------------------------------------------------------------------
# Detection & status
# ----------------------------------------------------------------------


async def test_status_when_r_available(monkeypatch):
    monkeypatch.setattr(r_service_module, "find_rscript", lambda: FAKE_SCRIPT)
    monkeypatch.setattr(r_service_module, "r_version", lambda path: "4.3.1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/v1/r/status")
    assert res.status_code == 200, res.text
    assert res.json() == {"available": True, "path": FAKE_SCRIPT, "version": "4.3.1"}


async def test_status_when_r_missing(monkeypatch):
    monkeypatch.setattr(r_service_module, "find_rscript", lambda: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/v1/r/status")
    assert res.status_code == 200, res.text
    assert res.json() == {"available": False, "path": None, "version": None}


def test_find_rscript_probes_standard_dirs(monkeypatch, tmp_path):
    rscript = tmp_path / "bin" / "Rscript.exe"
    rscript.parent.mkdir()
    rscript.write_text("", encoding="utf-8")
    (tmp_path / "bin" / "Rscript").write_text("", encoding="utf-8")
    monkeypatch.setattr(r_service_module, "which", lambda name: None)
    monkeypatch.setattr(r_service_module, "_standard_candidates", lambda: [rscript])
    assert r_service_module.find_rscript() == str(rscript)


def test_find_rscript_probes_r_home(monkeypatch, tmp_path):
    monkeypatch.delenv("R_HOME", raising=False)
    monkeypatch.setenv("R_HOME", str(tmp_path / "rhome"))
    rscript = tmp_path / "rhome" / "bin" / "Rscript.exe"
    rscript.parent.mkdir(parents=True)
    rscript.write_text("", encoding="utf-8")
    (tmp_path / "rhome" / "bin" / "Rscript").write_text("", encoding="utf-8")
    monkeypatch.setattr(r_service_module, "which", lambda name: None)
    monkeypatch.setattr(r_service_module, "_standard_candidates", list)
    expected = rscript if os.name == "nt" else tmp_path / "rhome" / "bin" / "Rscript"
    assert r_service_module.find_rscript() == str(expected)


def test_find_rscript_none_when_missing(monkeypatch):
    monkeypatch.delenv("R_HOME", raising=False)
    monkeypatch.setattr(r_service_module, "which", lambda name: None)
    monkeypatch.setattr(r_service_module, "_standard_candidates", list)
    assert r_service_module.find_rscript() is None


def test_r_version_parses_first_line(monkeypatch):
    class FakeResult:
        stdout = "R scripting front-end version 4.3.2 (2023-10-31)\nCopyright (C) 2023\n"
        stderr = ""

    monkeypatch.setattr(r_service_module.subprocess, "run", lambda *a, **k: FakeResult())
    assert r_service_module.r_version("whatever") == "4.3.2"


def test_r_version_none_on_failure(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("Rscript", 10)

    monkeypatch.setattr(r_service_module.subprocess, "run", boom)
    assert r_service_module.r_version("whatever") is None


def test_get_current_port_reads_newest(monkeypatch, tmp_path):
    f1 = tmp_path / "qualcoder-port-1.json"
    f2 = tmp_path / "qualcoder-port-2.json"
    f1.write_text(json.dumps({"port": 9001}), encoding="utf-8")
    f2.write_text(json.dumps({"port": 9002}), encoding="utf-8")
    os.utime(f1, (1, 1))
    os.utime(f2, (2, 2))
    monkeypatch.setattr(r_service_module, "_port_files", lambda: [str(f1), str(f2)])
    assert r_service_module.get_current_port() == 9002
    monkeypatch.setattr(r_service_module, "_port_files", list)
    assert r_service_module.get_current_port() == r_service_module.DEFAULT_PORT


def test_get_exchange_dir_creates_subdirs(tmp_path):
    exchange = r_service_module.get_exchange_dir(str(tmp_path))
    assert exchange == tmp_path / "r_exchange"
    for sub in ("in", "out", "logs"):
        assert (exchange / sub).is_dir()


# ----------------------------------------------------------------------
# Run submission guards
# ----------------------------------------------------------------------


async def test_run_requires_project():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/projects/close")
        res = await c.post("/api/v1/r/run", json={"script": "1 + 1"})
    assert res.status_code == 409


async def test_run_empty_script(project_client):
    client, _ = project_client
    res = await client.post("/api/v1/r/run", json={"script": "   "})
    assert res.status_code == 422


async def test_run_503_when_r_missing(project_client, monkeypatch):
    monkeypatch.setattr(r_service_module, "find_rscript", lambda: None)
    client, _ = project_client
    res = await client.post("/api/v1/r/run", json={"script": "1 + 1"})
    assert res.status_code == 503
    assert res.json()["error"] == "R not found — install R (r-project.org)"


# ----------------------------------------------------------------------
# Job lifecycle
# ----------------------------------------------------------------------


async def test_job_starts_queued_then_runs(monkeypatch, tmp_path):
    spawn = asyncio.Event()

    async def fake_spawn(*args, **kwargs):
        await spawn.wait()
        return FakeProcess(args, kwargs, stdout_lines=["ok"], stderr_lines=[])

    monkeypatch.setattr(r_service_module, "find_rscript", lambda: FAKE_SCRIPT)
    monkeypatch.setattr(r_service_module, "create_subprocess_exec", fake_spawn)
    job_id = r_service_module.start_r_job(project_path=str(tmp_path), script="x <- 1")
    try:
        # Before the event loop runs the task the job is queued.
        assert r_service_module.get_r_job(job_id)["state"] == "queued"
        spawn.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if r_service_module.get_r_job(job_id)["state"] in ("running", "done"):
                break
            await asyncio.sleep(0.05)
        assert r_service_module.get_r_job(job_id)["state"] == "done"
    finally:
        r_service_module.control_r_job(job_id, "cancel")


async def test_run_lifecycle_to_done(project_client, monkeypatch, tmp_path):
    spawned: list[FakeProcess] = []
    spawned_event = asyncio.Event()
    patch_r(monkeypatch, spawned=spawned, spawned_event=spawned_event)
    port = patch_port_file(monkeypatch, tmp_path)
    client, target = project_client
    script = "result <- 1 + 1\ncat('[1]', result, '\\n')\n"
    res = await client.post("/api/v1/r/run", json={"script": script})
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    await asyncio.wait_for(spawned_event.wait(), 5)
    assert spawned, "worker never spawned the subprocess"
    proc = spawned[0]

    # Spawn contract: Rscript args, exchange cwd and the QC_* env vars.
    assert proc.args[0] == FAKE_SCRIPT
    assert proc.args[1] == "--vanilla"
    assert proc.args[2] == "--encoding=UTF-8"
    assert proc.args[3].endswith(f"{job_id}.R")
    env = proc.kwargs["env"]
    assert env["QC_PORT"] == str(port)
    assert env["QC_PROJECT"] == str(target)
    assert env["QC_EXCHANGE"] == str(target / "r_exchange")
    assert proc.kwargs["cwd"] == str(target / "r_exchange" / "out")

    # The submitted script is persisted next to the run.
    script_file = target / "r_exchange" / "logs" / f"{job_id}.R"
    assert script_file.read_text(encoding="utf-8") == script

    body = await wait_for_job(client, job_id, {"done"})
    assert body["state"] == "done"
    assert body["message"] == "done"
    assert body["progress"] == 100.0
    assert body["exit_code"] == 0
    assert body["returncode"] == 0
    assert body["outputs"] == []
    assert "42" in body["stdout_tail"]
    assert body["stdout_tail"].endswith("done")
    # stdout/stderr are also captured to log files on disk.
    assert (target / "r_exchange" / "logs" / f"{job_id}.out").read_text(
        encoding="utf-8"
    ) == "[1] 42\ndone\n"
    assert (target / "r_exchange" / "logs" / f"{job_id}.err").exists()


async def test_job_collects_outputs(project_client, monkeypatch, tmp_path):
    gate = asyncio.Event()
    patch_r(monkeypatch, gate=gate)
    patch_port_file(monkeypatch, tmp_path)
    client, target = project_client
    res = await client.post("/api/v1/r/run", json={"script": "plot(1)\nwrite.csv(1, 'out.csv')\n"})
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    # The R side "writes" its artifacts into out/ before the run finishes.
    out_dir = target / "r_exchange" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    (out_dir / "out.csv").write_text("x\n1\n", encoding="utf-8", newline="\n")
    gate.set()

    body = await wait_for_job(client, job_id, {"done"})
    assert body["outputs"] == [
        {"name": "out.csv", "kind": "csv", "size": 4},
        {"name": "plot.png", "kind": "png", "size": 15},
    ]


async def test_job_error_state(project_client, monkeypatch, tmp_path):
    patch_r(monkeypatch, returncode=3)
    patch_port_file(monkeypatch, tmp_path)
    client, _ = project_client
    res = await client.post("/api/v1/r/run", json={"script": "stop('boom')\n"})
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    body = await wait_for_job(client, job_id, {"error"})
    assert body["state"] == "error"
    assert body["exit_code"] == 3
    assert body["returncode"] == 3
    assert body["message"] == "R exited with code 3"
    assert body["outputs"] == []


async def test_job_not_found(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/r/jobs/does-not-exist")
    assert res.status_code == 404


async def test_cancel_running_job(project_client, monkeypatch, tmp_path):
    gate = asyncio.Event()
    spawned: list[FakeProcess] = []
    spawned_event = asyncio.Event()
    patch_r(monkeypatch, gate=gate, spawned=spawned, spawned_event=spawned_event)
    patch_port_file(monkeypatch, tmp_path)
    client, _ = project_client
    res = await client.post("/api/v1/r/run", json={"script": "Sys.sleep(10)\n"})
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    await asyncio.wait_for(spawned_event.wait(), 5)
    assert spawned

    res = await client.delete(f"/api/v1/r/jobs/{job_id}")
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    assert spawned[0].terminated is True

    gate.set()
    body = await wait_for_job(client, job_id, {"cancelled"})
    assert body["state"] == "cancelled"
    assert body["outputs"] == []


async def test_cancel_finished_job_404(project_client, monkeypatch, tmp_path):
    patch_r(monkeypatch)
    patch_port_file(monkeypatch, tmp_path)
    client, _ = project_client
    res = await client.post("/api/v1/r/run", json={"script": "1 + 1\n"})
    job_id = res.json()["job_id"]
    await wait_for_job(client, job_id, {"done"})
    res = await client.delete(f"/api/v1/r/jobs/{job_id}")
    assert res.status_code == 404


# ----------------------------------------------------------------------
# Artifacts
# ----------------------------------------------------------------------


async def test_artifacts_list_and_serve(project_client, tmp_path):
    client, target = project_client
    out_dir = target / "r_exchange" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    png = b"\x89PNG\r\n\x1a\nartifact"
    (out_dir / "plot.png").write_bytes(png)
    (out_dir / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")

    res = await client.get("/api/v1/r/artifacts")
    assert res.status_code == 200, res.text
    files = res.json()["files"]
    assert [f["name"] for f in files] == ["data.csv", "plot.png"]
    by_name = {f["name"]: f for f in files}
    assert by_name["plot.png"]["kind"] == "png"
    assert by_name["plot.png"]["size"] == len(png)
    assert by_name["data.csv"]["kind"] == "csv"
    assert "modified" in by_name["data.csv"]

    got = await client.get("/api/v1/r/artifacts/plot.png")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.content == png

    got = await client.get("/api/v1/r/artifacts/data.csv")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("text/plain")
    assert got.content == b"a,b\n1,2\n"


async def test_artifacts_require_project():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/projects/close")
        res = await c.get("/api/v1/r/artifacts")
    assert res.status_code == 409


@pytest.mark.parametrize(
    "name",
    [
        "..%2Fsecret.csv",
        "..%5Csecret.csv",
        "sub%2Fplot.png",
        "..",
        "missing.csv",
        "notes.txt",
    ],
)
async def test_artifact_traversal_and_missing_404(project_client, name):
    client, _ = project_client
    res = await client.get(f"/api/v1/r/artifacts/{name}")
    assert res.status_code == 404
