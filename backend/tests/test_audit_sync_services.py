"""Regression tests for the sync/services audit fixes."""

from __future__ import annotations

import asyncio
import json
import time
import zipfile

import pytest

from qualcoder_api.services import minisign

# ── minisign: RFC 8032 point decoding ────────────────────────────────────


def _off_curve_encoding() -> bytes:
    """A canonical y whose x² is a non-residue (no point on the curve)."""
    q, d = minisign._Q, minisign._D
    for y in range(2, 1000):
        xx = (y * y - 1) * pow(d * y * y + 1, q - 2, q) % q
        x = minisign._xrecover(y)
        if (x * x - xx) % q != 0:
            return y.to_bytes(32, "little")
    raise AssertionError("no off-curve y found")


def test_decode_point_rejects_off_curve_y() -> None:
    assert minisign._decode_point(_off_curve_encoding()) is None


def test_decode_point_rejects_negative_zero_x() -> None:
    # y = 1 is the identity (x = 0); the sign bit set is non-canonical.
    enc = bytearray((1).to_bytes(32, "little"))
    enc[31] |= 0x80
    assert minisign._decode_point(bytes(enc)) is None
    assert minisign._decode_point((1).to_bytes(32, "little")) is not None


def test_verify_still_accepts_valid_and_rejects_off_curve_r() -> None:
    pub, sec = minisign.generate_keypair()
    sig_b64 = minisign.sign_message(sec, b"patch")
    assert minisign.verify_message(pub, b"patch", sig_b64)
    _, sig = minisign.parse_signature(sig_b64)
    bad = _off_curve_encoding() + sig[32:]
    _, pubkey = minisign.parse_pubkey(pub)
    assert not minisign.ed25519_verify(pubkey, b"patch", bad)


# ── hotpatch: zip containment ────────────────────────────────────────────


def test_safe_unpack_rejects_sibling_prefix_escape(tmp_path) -> None:
    from qualcoder_api.services.hotpatch import HotpatchError, safe_unpack

    zpath = tmp_path / "p.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../unpacked2/evil.txt", "x")
    dest = tmp_path / "unpacked"
    dest.mkdir()
    with pytest.raises(HotpatchError):
        safe_unpack(zpath, dest)
    assert not (tmp_path / "unpacked2").exists()


# ── session_manager: acquire vs close race ───────────────────────────────


async def test_acquire_does_not_return_service_closed_by_concurrent_close(monkeypatch) -> None:
    from qualcoder_api.services import session_manager as sm

    gate = asyncio.Event()
    opened: list = []

    class FakeResult:
        ok = True
        error = None

    class FakeService:
        def __init__(self) -> None:
            self.closed = False

        async def open_project(self, path, codername=""):
            opened.append(self)
            if len(opened) == 1:
                await gate.wait()
            return FakeResult()

        async def close_project(self):
            self.closed = True

    async def get_project(pid):
        return {"data_path": "/x"}

    async def get_member(pid, uid):
        return None

    monkeypatch.setattr(sm, "ProjectService", FakeService)
    monkeypatch.setattr(sm.metadata_db, "get_project", get_project)
    monkeypatch.setattr(sm.metadata_db, "get_member", get_member)

    mgr = sm.SessionManager()
    user = {"id": 1, "username": "u", "role": "admin"}
    t1 = asyncio.create_task(mgr.acquire(user, "p"))
    for _ in range(5):
        await asyncio.sleep(0)
    t2 = asyncio.create_task(mgr.acquire(user, "p"))  # queues on the lock
    for _ in range(5):
        await asyncio.sleep(0)
    t3 = asyncio.create_task(mgr.close("p"))  # pops the entry, queues
    for _ in range(5):
        await asyncio.sleep(0)
    gate.set()
    (svc1, _), (svc2, _), _ = await asyncio.gather(t1, t2, t3)

    assert svc1.closed  # the close took the first session down
    assert not svc2.closed  # the second request got a live service ...
    assert mgr.sessions["p"].service is svc2  # ... that the pool tracks


# ── session_service: prune with open sessions ────────────────────────────


def test_prune_sessions_handles_open_sessions_and_keeps_their_acks(tmp_path) -> None:
    from qualcoder_api.services import session_service as ss

    project = str(tmp_path)
    open_id = ss.create_session(project, "alice", instance_id="inst01")
    old_id = ss.create_session(project, "bob", instance_id="inst02")
    old_path = ss._session_path(project, old_id)
    data = json.loads(old_path.read_text(encoding="utf-8"))
    data.update(closed=True, closed_at=time.time() - ss.SESSION_TTL_SECS * 3)
    old_path.write_text(json.dumps(data), encoding="utf-8")
    open_acks = ss._acks_dir(project) / open_id
    open_acks.mkdir(parents=True)
    (open_acks / "peer.json").write_text("{}", encoding="utf-8")

    assert ss.prune_sessions(project) == 1
    assert not old_path.exists()
    assert ss._session_path(project, open_id).exists()
    assert (open_acks / "peer.json").exists()


# ── backup_service: archive name ─────────────────────────────────────────


def test_backup_archive_name_is_one_component() -> None:
    from qualcoder_api.services.backup_service import _safe_filename

    assert _safe_filename("../../etc/evil") == "etc_evil"
    assert "/" not in _safe_filename("a/b\\c") and "\\" not in _safe_filename("a/b\\c")
    assert _safe_filename("..") == "project"
    assert _safe_filename("My Study 2026") == "My_Study_2026"
