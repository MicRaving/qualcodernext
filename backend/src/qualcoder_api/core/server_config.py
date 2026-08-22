"""Server-mode configuration — the single source of truth for env vars.

Server mode (``QC_SERVER_MODE=true``) turns the same backend into a
multi-tenant deployment: project sessions, auth, backups. In local mode
every value here is inert; nothing in the desktop code path reads these
env vars (invariant #3 of docs/SERVER_PLAN.md).

No other module may read these env vars directly — import from here.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def is_server_mode() -> bool:
    """True when the backend runs as a multi-tenant server."""
    return os.environ.get("QC_SERVER_MODE", "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ServerConfig:
    data_dir: Path
    metadata_db: Path
    secret_key: str | None
    token_ttl_secs: int
    cors_origins: list[str]
    session_idle_secs: int
    max_upload_bytes: int
    backup_retention: str
    rclone_conf: str
    rclone_remote: str
    rp_id: str | None
    rp_origin: str | None

    @property
    def projects_root(self) -> Path:
        return self.data_dir / "projects"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "temp"

    @property
    def backups_root(self) -> Path:
        return self.data_dir / "backups" / "local"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_server_config() -> ServerConfig:
    """Read every server env var once. Call at startup (server mode only)."""
    data_dir = Path(os.environ.get("QC_DATA_DIR", "./data")).resolve()
    rp_id = os.environ.get("QC_RP_ID", "").strip() or None
    return ServerConfig(
        data_dir=data_dir,
        metadata_db=Path(
            os.environ.get("QC_METADATA_DB", str(data_dir / "metadata" / "qualcoder.db"))
        ).resolve(),
        secret_key=os.environ.get("QC_SECRET_KEY") or None,
        token_ttl_secs=_int_env("QC_TOKEN_TTL_SECS", 604800),
        cors_origins=[
            o.strip() for o in os.environ.get("QC_CORS_ORIGINS", "").split(",") if o.strip()
        ],
        session_idle_secs=_int_env("QC_SESSION_IDLE_SECS", 900),
        max_upload_bytes=_int_env("QC_MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024),
        backup_retention=os.environ.get("QC_BACKUP_RETENTION", "daily=14,weekly=8,monthly=12"),
        rclone_conf=os.environ.get("QC_RCLONE_CONF", "/etc/rclone/rclone.conf"),
        rclone_remote=os.environ.get("QC_RCLONE_REMOTE", "qcnext-crypt:"),
        rp_id=rp_id,
        rp_origin=os.environ.get("QC_RP_ORIGIN", "").strip() or (f"https://{rp_id}" if rp_id else None),
    )


class ServerConfigError(RuntimeError):
    """Raised at startup when required server configuration is missing."""


def validate_server_config(config: ServerConfig) -> None:
    """Fail fast with a clear message when required settings are missing."""
    if not config.secret_key:
        raise ServerConfigError(
            "QC_SERVER_MODE is enabled but QC_SECRET_KEY is not set. "
            "Generate one e.g. with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )


def resolve_under_root(root: Path, name: str) -> Path:
    """Resolve ``name`` under ``root``, refusing path escapes.

    Rejects absolute paths, ``..`` traversal and (after resolution) any
    result that is not actually contained in ``root`` — server mode never
    accepts a client-supplied filesystem path (plan invariant #5).
    """
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path escapes the managed root: {name!r}")
    resolved = (root / candidate).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"path escapes the managed root: {name!r}")
    return resolved


def project_dir(project_id: str) -> Path:
    """The managed directory of a project id (uuid4 hex, validated)."""
    if not project_id or not re.fullmatch(r"[0-9a-f]{32}", project_id):
        raise ValueError(f"invalid project id: {project_id!r}")
    return resolve_under_root(load_server_config().projects_root, project_id)

