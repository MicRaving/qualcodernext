"""Regression tests for the AI/services audit (scrape SSRF, transcription
sidecar persistence, R output pump, native delta path validation)."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from qualcoder_api.services import native, r_service, scrape_service
from qualcoder_api.services import transcription as tr
from qualcoder_api.services.hotpatch import HotpatchError
from qualcoder_api.services.scrape_service import ScrapeError


def _fake_getaddrinfo(ip: str):
    def _impl(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _impl


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "::ffff:127.0.0.1"])
def test_fetch_url_rejects_names_resolving_to_private_hosts(ip):
    with (
        patch.object(scrape_service.socket, "getaddrinfo", _fake_getaddrinfo(ip)),
        patch.object(scrape_service.urllib.request, "build_opener") as opener,
        pytest.raises(ScrapeError, match="private or local"),
    ):
        scrape_service.fetch_url("http://localtest.me/")
    opener.assert_not_called()


def test_resolution_failure_is_not_treated_as_blocked():
    def _fail(*_a, **_k):
        raise socket.gaierror("no dns")

    with patch.object(scrape_service.socket, "getaddrinfo", _fail):
        assert scrape_service._resolves_to_blocked_host("http://example.org/") is False


def test_fetch_url_maps_read_timeout_to_scrape_error():
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *_a):
            raise TimeoutError("timed out")

    class _Opener:
        def open(self, *_a, **_k):
            return _Resp()

    with (
        patch.object(scrape_service.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34")),
        patch.object(scrape_service.urllib.request, "build_opener", return_value=_Opener()),
        pytest.raises(ScrapeError, match="could not fetch"),
    ):
        scrape_service.fetch_url("http://example.org/")


def test_redirect_to_non_http_scheme_is_refused():
    import urllib.request

    handler = scrape_service._SsrfRedirectHandler()
    req = urllib.request.Request("http://example.org/")
    with pytest.raises(ScrapeError, match="non-http"):
        handler.redirect_request(req, None, 302, "Found", {}, "ftp://example.org/x")


def test_transcription_worker_persists_sidecar(tmp_path, monkeypatch):
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    monkeypatch.setattr(tr, "_transcribe_whisper", lambda *_a: segments)
    job_id = "auditjob0001"
    start, pause, cancel = threading.Event(), threading.Event(), threading.Event()
    start.set()
    pause.set()
    with tr._jobs_lock:
        tr._JOBS[job_id] = {
            "id": job_id,
            "state": "running",
            "result": None,
            "_start": start,
            "_pause": pause,
            "_cancel": cancel,
            "project_path": str(tmp_path),
            "source_id": 7,
        }
    try:
        tr._run_worker(job_id, "ignored.wav", {})
        sidecar = tmp_path / "_transcripts" / f"{job_id}.json"
        assert sidecar.is_file()
        assert json.loads(sidecar.read_text(encoding="utf-8"))["segments"] == segments
        job = tr.get_job(job_id)
        assert job["state"] == "done" and job["result"] == segments
    finally:
        with tr._jobs_lock:
            tr._JOBS.pop(job_id, None)


def test_r_pump_survives_overlong_line(tmp_path):
    async def _run() -> str:
        stream = asyncio.StreamReader(limit=64)
        stream.feed_data(b"x" * 500 + b"\nafter\n")
        stream.feed_eof()
        job_id = "rpumpaudit01"
        with r_service._jobs_lock:
            r_service._JOBS[job_id] = {"id": job_id}
        try:
            await r_service._pump(job_id, stream, "stdout_tail", tmp_path / "out.log")
            return r_service._JOBS[job_id]["stdout_tail"]
        finally:
            with r_service._jobs_lock:
                r_service._JOBS.pop(job_id, None)

    tail = asyncio.run(_run())
    assert "after" in tail
    assert "truncated" in tail


@pytest.mark.parametrize(
    "bad", ["../evil.dll", "a/../../evil", "/etc/passwd", "C:\\Windows\\x.dll", "a\\..\\..\\x", ""]
)
def test_native_rejects_unsafe_relpaths(tmp_path: Path, bad):
    (tmp_path / "delta.json").write_text(
        json.dumps({"from": "1.0.0", "to": "1.0.0_001", "files": [], "deleted": [bad]}),
        encoding="utf-8",
    )
    with pytest.raises(HotpatchError, match="unsafe"):
        native._verify_staged(tmp_path, "1.0.0_001", "1.0.0")


def test_native_accepts_plain_relpaths(tmp_path: Path):
    (tmp_path / "delta.json").write_text(
        json.dumps({"from": "1.0.0", "to": "1.0.0_001", "files": [], "deleted": ["lib/x.dll"]}),
        encoding="utf-8",
    )
    assert native._verify_staged(tmp_path, "1.0.0_001", "1.0.0")["deleted"] == ["lib/x.dll"]
