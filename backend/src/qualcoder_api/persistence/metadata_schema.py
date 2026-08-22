"""Metadata SQLite schema — DDL and ordered migrations (SERVER_PLAN.md §6.1).

The metadata DB holds server-domain state only: users, passkeys, tokens,
the project registry with memberships, backup records, the server audit
log and WebAuthn challenges. Project DATA lives in each project's own
.qda SQLite database — never here.
"""
from __future__ import annotations

# Ordered migrations. Each entry runs once; applied versions are tracked in
# schema_version(version INTEGER). Migrations must be idempotent-safe by
# construction (IF NOT EXISTS) so a crash between DDL and version bump
# cannot wedge startup.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE IF NOT EXISTS users (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL DEFAULT '',
  email       TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL DEFAULT '',
  role        TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
  disabled    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passkeys (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  credential_id TEXT NOT NULL UNIQUE,
  public_key   TEXT NOT NULL,
  sign_count   INTEGER NOT NULL DEFAULT 0,
  transports   TEXT NOT NULL DEFAULT '',
  name         TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_tokens (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL DEFAULT '',
  expires_at  TEXT NOT NULL,
  revoked     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  last_used_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  owner_id    INTEGER NOT NULL REFERENCES users(id),
  data_path   TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleting')),
  size_bytes  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_members (
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('owner','editor','viewer')),
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS backup_records (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN ('manual','scheduled')),
  local_path  TEXT NOT NULL,
  size_bytes  INTEGER NOT NULL DEFAULT 0,
  checksum    TEXT NOT NULL DEFAULT '',
  cloud_status TEXT NOT NULL DEFAULT 'pending'
              CHECK (cloud_status IN ('pending','uploaded','failed','skipped')),
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS server_audit (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER,
  project_id  TEXT,
  action      TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webauthn_challenges (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  challenge   TEXT NOT NULL UNIQUE,
  user_id     INTEGER,
  kind        TEXT NOT NULL CHECK (kind IN ('register','login')),
  expires_at  TEXT NOT NULL
);
""",
    ),
]
