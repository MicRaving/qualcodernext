"""Shared security helpers — filename sanitization, id validation, SSRF guards."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse

_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_RESERVED_INSTANCES = frozenset({"__server__"})

# SQL write keywords blocked by the read-only report gate.
_SQL_WRITE_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|VACUUM|REINDEX|"
    r"REPLACE|TRIGGER|GRANT|REVOKE|ANALYZE|PRAGMA)\b",
    re.IGNORECASE,
)

# Hosts that must never be fetched server-side (SSRF).
_SSRF_BLOCKED_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"}
)


def sanitize_filename(name: str | None, fallback: str = "upload") -> str:
    """Return a safe basename for a client-supplied upload filename."""
    if not name:
        return fallback
    # Strip directories, NUL bytes, and surrounding whitespace.
    base = Path(str(name)).name.replace("\x00", "").strip()
    if base in ("", ".", ".."):
        return fallback
    # Remove path separators that survived (Windows alt separator).
    base = base.replace("/", "_").replace("\\", "_")
    # Keep it reasonably short for filesystem limits.
    if len(base) > 255:
        suffix = Path(base).suffix[:16]
        base = base[: 255 - len(suffix)] + suffix
    return base or fallback


def validate_instance_id(instance_id: str) -> str:
    """Validate a sync instance/session id; raises ValueError when unsafe."""
    if not instance_id or not _INSTANCE_ID_RE.match(instance_id):
        raise ValueError(f"invalid instance id: {instance_id!r}")
    if ".." in instance_id or "/" in instance_id or "\\" in instance_id:
        raise ValueError(f"invalid instance id: {instance_id!r}")
    return instance_id


def validate_session_id(session_id: str) -> str:
    """Same rules as instance ids (sessions share the sidecar namespace)."""
    return validate_instance_id(session_id)


def is_reserved_instance(instance_id: str) -> bool:
    return instance_id in _RESERVED_INSTANCES


def assert_safe_zip_names(names: list[str]) -> None:
    """Raise ValueError when a zip archive contains traversal entries."""
    for name in names:
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"unsafe zip entry: {name}")
        # Reject absolute Windows paths and drive letters.
        if re.match(r"^[A-Za-z]:", name) or name.startswith(("\\\\", "\\")):
            raise ValueError(f"unsafe zip entry: {name}")


def is_ssrf_blocked_url(url: str) -> bool:
    """True when a URL targets a host that must never be fetched server-side."""
    try:
        host = (urlparse(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return True
    if not host:
        return True
    if host in _SSRF_BLOCKED_HOSTS:
        return True
    # Block cloud metadata IP explicitly (also covered by private check).
    if host in ("169.254.169.254", "213.0.0.0"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        pass
    # Hostnames resolving to localhost-ish names.
    return host.endswith((".local", ".internal"))


def validate_mcp_command(command: str | None, args: list[str] | None) -> None:
    """Validate an external MCP stdio command; raises ValueError when unsafe."""
    if command is None:
        return
    cmd = command.strip()
    if not cmd:
        return
    if len(cmd) > 512:
        raise ValueError("mcp server command too long")
    if "\x00" in cmd or "\n" in cmd or "\r" in cmd:
        raise ValueError("invalid mcp server command")
    if args is not None:
        if len(args) > 64:
            raise ValueError("too many mcp server args")
        for a in args:
            if not isinstance(a, str) or len(a) > 1024 or "\x00" in a:
                raise ValueError("invalid mcp server arg")


def validate_read_only_sql(sql: str) -> str:
    """Validate ad-hoc SQL is a single read-only statement; returns stripped stmt."""
    stmt = sql.strip().rstrip(";").strip()
    if not stmt:
        raise ValueError("query is empty")
    if len(stmt) > 20000:
        raise ValueError("query too long")
    parts = stmt.split(None, 1)
    if not parts or parts[0].upper() not in {"SELECT", "WITH", "VALUES", "EXPLAIN"}:
        raise ValueError("Only read-only queries are allowed")
    if ";" in stmt or "--" in stmt or "/*" in stmt:
        raise ValueError("Multiple statements are not allowed")
    if _SQL_WRITE_RE.search(stmt):
        raise ValueError("Only read-only queries are allowed")
    return stmt


def append_limit(stmt: str, max_rows: int) -> str:
    """Cap rows without breaking existing LIMIT/OFFSET clauses."""
    if re.search(r"\bLIMIT\b", stmt, re.IGNORECASE):
        return stmt
    return f"{stmt} LIMIT {max_rows + 1}"
