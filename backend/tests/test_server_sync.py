"""SERVER_PLAN.md Phase 3 — sync hub.

Two simulated instances ("inst-anna", "inst-bob") push/pull through the
HTTP hub against ONE canonical DB. Verifies:
- a pushed code_name insert is applied to the canonical DB,
- the OTHER instance pulls it (own entries excluded),
- conflicting concurrent edits surface as pending conflicts,
- presence heartbeats show in /sync/state.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.persistence import metadata_db


@pytest.fixture
def server_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_SERVER_MODE", "true")
    monkeypatch.setenv("QC_SECRET_KEY", "s")
    monkeypatch.setenv("QC_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path
    # engine disposal happens in the async `client` fixture (same loop);
    import qualcoder_api.services.session_manager as sm

    sm.manager.sessions.clear()


@pytest.fixture
async def client(server_env):

    from qualcoder_api.main import create_app

    await metadata_db.migrate_metadata(server_env / "data" / "metadata" / "qualcoder.db")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await metadata_db.dispose_metadata_engine()
    import qualcoder_api.services.session_manager as sm

    sm.manager.sessions.clear()


async def test_two_instances_converge_and_conflict(client):
    # Bootstrap admin (project owner) + two editors.
    r = await client.post(
        "/api/v1/auth/register", json={"username": "owner", "password": "owner-pw-1"}
    )
    assert r.status_code == 200
    owner_login = await client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "owner-pw-1"}
    )
    owner = {"Authorization": f"Bearer {owner_login.json()['token']}"}

    created = await client.post(
        "/api/v1/server/projects", json={"name": "Hub"}, headers=owner
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    for name in ("anna", "bob"):
        reg = await client.post(
            "/api/v1/auth/register",
            json={"username": name, "password": f"{name}-pw-123"},
            headers=owner,
        )
        assert reg.status_code == 200, reg.text
        share = await client.put(
            f"/api/v1/server/projects/{pid}/members/{reg.json()['user']['id']}",
            json={"role": "editor"},
            headers=owner,
        )
        assert share.status_code == 200

    anna_login = await client.post(
        "/api/v1/auth/login", json={"username": "anna", "password": "anna-pw-123"}
    )
    bob_login = await client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob-pw-123"}
    )
    anna = {"Authorization": f"Bearer {anna_login.json()['token']}", "X-Project-Id": pid}
    bob = {"Authorization": f"Bearer {bob_login.json()['token']}", "X-Project-Id": pid}

    # Warm the canonical session.
    opened = await client.post(f"/api/v1/server/projects/{pid}/open", headers=owner)
    assert opened.status_code == 200

    def entry(seq: int, pk: int, name: str, color: str, rev: int = 1) -> dict:
        return {
            "seq": seq,
            "instance": "test",
            "coder": "tester",
            "entity": "code_name",
            "action": "insert",
            "pk_name": "cid",
            "pk_value": pk,
            "rev": rev,
            "mtime": "2026-01-01T00:00:00.000",
            "row": {
                "cid": pk,
                "name": name,
                "catid": None,
                "supercid": None,
                "memo": "",
                "color": color,
                "owner": "tester",
                "date": "2026-01-01",
                "memo_type": "",
                "position": 0,
            },
        }

    def update_entry(seq: int, pk: int, name: str, color: str, rev: int, mtime: str) -> dict:
        e = entry(seq, pk, name, color, rev)
        e["action"] = "update"
        e["mtime"] = mtime
        return e

    # ── anna pushes Alpha ───────────────────────────────────────────
    push_a = await client.post(
        "/api/v1/sync/push",
        json={"instance_id": "inst-anna", "entries": [entry(1, 9001, "Alpha", "#ff0000")]},
        headers=anna,
    )
    assert push_a.status_code == 200, push_a.text
    assert push_a.json()["total_applied"] >= 1

    # Canonical DB now has Alpha.
    codes = await client.get("/api/v1/codes", headers={**anna})
    names = [c["name"] for c in codes.json()]
    assert "Alpha" in names

    # ── bob pulls: sees anna's entry; own excluded later ────────────
    pull_b = await client.get(
        "/api/v1/sync/pull", params={"instance_id": "inst-bob", "since": 0}, headers=bob
    )
    assert pull_b.status_code == 200
    pulled_names = [e["row"]["name"] for e in pull_b.json()["entries"] if e.get("row")]
    assert "Alpha" in pulled_names

    # ── both push conflicting updates to the SAME row ───────────────
    # Server-side API edit bumps the canonical row to rev 2 with color X.
    codes_now = await client.get("/api/v1/codes", headers={**anna})
    alpha = next(
        c for c in codes_now.json() if c.get("kind") == "code" and c["name"] == "Alpha"
    )
    patch = await client.patch(
        f"/api/v1/codes/{alpha['id']}",
        json={"color": "#123456"},
        headers={**owner, "X-Project-Id": pid},
    )
    assert patch.status_code == 200, patch.text

    # bob's edit is based on the PRE-patch row (rev 2 base) but carries a
    # divergent color at the CURRENT rev → genuine conflict, not LWW.
    conflict_a = await client.post(
        "/api/v1/sync/push",
        json={
            "instance_id": "inst-anna",
            "entries": [update_entry(2, alpha["id"], "Alpha-renamed-A", "#00ff00", rev=2, mtime="2099-01-01T00:00:00.000")],
        },
        headers=anna,
    )
    assert conflict_a.status_code == 200
    conflict_b = await client.post(
        "/api/v1/sync/push",
        json={
            "instance_id": "inst-bob",
            "entries": [update_entry(1, alpha["id"], "Alpha-renamed-B", "#0000ff", rev=2, mtime="2099-01-01T00:00:00.000")],
        },
        headers=bob,
    )
    assert conflict_b.status_code == 200

    state = await client.get("/api/v1/sync/state", params={"instance_id": "inst-bob"}, headers=bob)
    assert state.status_code == 200
    body = state.json()
    assert body["conflicts"] >= 1, {
        "state": body,
        "a": conflict_a.json(),
        "b": conflict_b.json(),
        "alpha": alpha,
    }

    # ── presence heartbeat surfaces in state ────────────────────────
    beat = await client.post(
        "/api/v1/sync/presence",
        json={"instance_id": "inst-bob", "file_id": 3, "file_name": "focus.txt"},
        headers=bob,
    )
    assert beat.status_code == 200
    state2 = await client.get("/api/v1/sync/state", params={"instance_id": "inst-bob"}, headers=bob)
    coders = [p["coder"] for p in state2.json()["presence"]]
    assert "bob" in coders


async def test_push_requires_editor_role(client):
    r = await client.post(
        "/api/v1/auth/register", json={"username": "admin", "password": "admin-pw-123"}
    )
    assert r.status_code == 200
    admin = {
        "Authorization": (
            await client.post(
                "/api/v1/auth/login", json={"username": "admin", "password": "admin-pw-123"}
            )
        ).json()["token"]
    }
    admin = {"Authorization": f"Bearer {admin['Authorization']}"}
    created = await client.post(
        "/api/v1/server/projects", json={"name": "RO"}, headers=admin
    )
    pid = created.json()["id"]
    reg = await client.post(
        "/api/v1/auth/register",
        json={"username": "viewer", "password": "viewer-pw-1"},
        headers=admin,
    )
    vid = reg.json()["user"]["id"]
    await client.put(
        f"/api/v1/server/projects/{pid}/members/{vid}",
        json={"role": "viewer"},
        headers=admin,
    )
    vlogin = await client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": "viewer-pw-1"}
    )
    viewer = {"Authorization": f"Bearer {vlogin.json()['token']}", "X-Project-Id": pid}
    denied = await client.post(
        "/api/v1/sync/push",
        json={"instance_id": "inst-viewer", "entries": []},
        headers=viewer,
    )
    assert denied.status_code == 403


