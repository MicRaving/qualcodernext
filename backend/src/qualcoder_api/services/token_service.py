"""Opaque bearer tokens — sha256-hashed at rest (SERVER_PLAN.md §6.3).

The raw token is returned exactly once at issue time and never stored or
logged; only its sha256 hex digest lives in ``auth_tokens``.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from qualcoder_api.core.server_config import load_server_config
from qualcoder_api.persistence import metadata_db


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


async def issue_token(user_id: int, name: str = "") -> tuple[str, str]:
    """Create a token; returns ``(raw_token, expires_at_iso)``."""
    raw = secrets.token_urlsafe(32)
    ttl = load_server_config().token_ttl_secs
    expires_at = _iso(datetime.now(UTC) + timedelta(seconds=ttl))
    await metadata_db.record_token(user_id, _hash(raw), expires_at, name=name)
    return raw, expires_at


async def verify_token(raw: str) -> int | None:
    """The owning user id, or None when unknown/expired/revoked/disabled.

    Lazily prunes dead rows on every check so the table cannot grow
    unbounded with abandoned sessions.
    """
    if not raw:
        return None
    await metadata_db.prune_expired_tokens()
    row = await metadata_db.lookup_token(_hash(raw))
    return int(row["user_id"]) if row else None


async def revoke_token(raw: str) -> None:
    await metadata_db.revoke_token(_hash(raw))


async def revoke_all_for_user(user_id: int) -> None:
    await metadata_db.revoke_all_for_user(user_id)
