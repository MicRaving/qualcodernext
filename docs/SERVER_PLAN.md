# QualCoder v4 — Server Deployment: Full Implementation Plan

> **Implementation status:** Phase 0 (infrastructure scaffolding) is
> **implemented** (`core/server_config.py`, lifespan gating in `main.py`,
> `deps.CURRENT_SERVICE` ContextVar, `tests/test_server_config.py`).
> **Phase 1 core is implemented**: metadata DB + migrations
> (`persistence/metadata_schema.py`, `metadata_db.py`), password hashing
> (`services/password.py`, argon2id), opaque tokens
> (`services/token_service.py`), auth API (register/login/logout/refresh/
> me, admin user-disable; `api/v1/auth.py` + `auth_deps.py`, mounted only
> in server mode) — `tests/test_auth_api.py`.
> **Phase 1b remains:** passkey endpoints (WebAuthn; lib installed,
> service layer pending). Phases 2–5 are not started and must each land as
> their own change, passing their acceptance checklist before the next.

Audience: an implementer model (e.g. MiMo-class). This document is written to
be followed mechanically: each phase lists exact files to create/modify, exact
endpoint signatures, exact SQL, and an acceptance checklist. Do **not** write
code while planning; this document is the plan to review first.

---

## 0. Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Multi-tenancy | **Option A** — in-process project-session pool (no process-per-session) |
| 2 | Metadata DB | **SQLite**; exactly one server process may write a project at a time |
| 3 | Auth | **Opaque hashed DB tokens** + **passkeys (WebAuthn)** |
| 4 | Cloud backup | **Hybrid**: local-first snapshots + `rclone` mirror, `crypt`-encrypted, target **Nextcloud (WebDAV)** |
| 5 | Identity | **Coder name == server username** (1:1, enforced) |
| 6 | Topology | **Single Docker host** (compose) |

## 1. Non-negotiable invariants

These must hold at the end of every phase. Any change that breaks them is wrong.

1. **The local-first desktop app keeps working exactly as today.** Running the
   backend with server mode OFF (`QC_SERVER_MODE` unset/false) must produce
   byte-identical behavior to the current build. All 994 existing backend tests
   stay green with server mode OFF.
2. **Single codebase.** The server is a *deployment mode* of the same backend,
   not a fork. New features written for the local app appear on the server
   automatically, because both serve the same routers and `services/` layer.
3. **No shared global state between local and server mode.** `~/.qualcoder/`
   remains the local app's config home and is **never** read or written in
   server mode. Server uses `QC_DATA_DIR` and env vars only.
4. **One writer per project.** A single server process owns a project at a time
   (guaranteed by an in-process per-project lock + a `server.lock` marker file).
   Horizontal scaling is out of scope and explicitly rejected at startup.
5. **Path confinement.** Server mode never accepts a client-supplied filesystem
   path. Every path is derived from `project_id` and resolved under `QC_DATA_DIR`.
6. **Collaboration transport swaps, logic does not.** `sync_engine` replay,
   natural-key matching, and conflict resolution are reused unchanged; only the
   transport (shared folder → HTTP) changes, and only when server mode is on.

---

## 2. Architecture (how "server inherits local features" works)

```
Browsers / desktop clients
        │  Authorization: Bearer <token>   X-Project-Id: <uuid>
        ▼
Reverse proxy (Caddy, TLS)  →  serves static frontend + /api/v1
        ▼
FastAPI app (same codebase)
  ├─ server mode ON:
  │    auth_deps.resolve_project_service()   (validates token + ACL)
  │      → SessionManager.get(project_id)    (opens ProjectService if needed)
  │      → sets ContextVar → existing ServiceDep reads it
  │    existing project-scoped routers (sources/codes/codings/…) unchanged
  │    + new: auth, projects registry, upload/download, sync hub, backups, admin
  └─ server mode OFF: identical to today (global ProjectService singleton)
        │
Project storage  /data/qualcoder/projects/<project_id>/<name>.qda/
Metadata (SQLite) /data/qualcoder/metadata/qualcoder.db
Backups  /data/qualcoder/backups/local/<project_id>/…   → rclone → Nextcloud(crypt)
```

**Mechanism for "no/low effort inheritance":**

- All project-scoped business logic lives in `backend/src/qualcoder_api/services/*`.
  The server **does not reimplement** any of it; it calls the same
  `ProjectService` methods (`open_project`, `close_project`, repositories, etc.).
- The existing endpoint layer keeps using `ServiceDep` (= `get_service()`).
  We only change **what `get_service()` returns** in server mode: a
  request-scoped `ProjectService` resolved from a `ContextVar`, instead of the
  global singleton in `main.py`.
- Therefore any future feature added as a `services/*` function + router call is
  immediately available on the server with zero extra work.

---

## 3. Repository map (new vs modified)

### New files (backend)

```
backend/src/qualcoder_api/
  core/server_config.py            # env-driven config (single source of truth)
  persistence/metadata_db.py       # engine/factory for metadata SQLite + migrations
  persistence/metadata_schema.py   # DDL for users/passkeys/tokens/projects/members/backups/audit
  services/metadata_repo.py        # CRUD for users/tokens/projects/members (bcrypt/argon2)
  services/password.py             # password hash/verify (argon2-cffi)
  services/token_service.py        # opaque token issue/verify/revoke (sha256 hashes)
  services/passkey_service.py      # WebAuthn registration + assertion (webauthn lib)
  services/session_manager.py      # project-session pool + ContextVar + per-project lock
  services/backup_service.py       # snapshot + restore + retention
  services/backup_scheduler.py     # background schedule + on-demand trigger
  api/v1/auth_deps.py              # get_current_user, require_role, resolve_project_service
  api/v1/auth.py                   # login/register/passkey/logout/refresh/me endpoints
  api/v1/server_projects.py        # project registry + share/ACL + upload/download endpoints
  api/v1/server_backups.py         # backup list/run/restore endpoints (admin/owner)
  api/v1/server_admin.py           # user administration (admin)
  api/v1/server_sync.py            # collaboration sync hub (push/pull/presence)
  cli.py                           # manage.py-style CLI: bootstrap-admin, backup, migrate
backend/tests/
  test_server_config.py  test_metadata_db.py  test_token_service.py
  test_password.py  test_passkey_service.py  test_session_manager.py
  test_auth_api.py  test_server_projects.py  test_server_backups.py
  test_server_sync.py  test_server_admin.py
backend/scripts/
  docker-entrypoint.sh   cloud-backup.sh   rclone.conf.template
backend/Dockerfile  backend/docker-compose.yml  backend/.env.example
```

### New files (frontend)

```
frontend/src/features/auth/          # Login screen, passkey UI, token storage, logout
frontend/src/lib/api/authClient.ts   # auth calls + Authorization header + X-Project-Id
frontend/src/lib/session.ts          # token storage (Tauri secure store / localStorage fallback)
frontend/src/features/server/        # Projects list, upload/download, share, backups UI
```

### Modified files (backend)

```
backend/src/qualcoder_api/main.py                 # mode wiring, lifespan, lifespan gating
backend/src/qualcoder_api/api/v1/deps.py          # get_service() reads ContextVar in server mode
backend/src/qualcoder_api/api/v1/router.py        # server-mode dependency wrapper; register new routers
backend/src/qualcoder_api/services/project_service.py  # add server.lock; codername==username enforcement hook
backend/src/qualcoder_api/services/sync_engine.py # transport indirection (no logic change)
backend/src/qualcoder_api/services/sync.py        # server-mode sync_enabled + detect_shared override
backend/src/qualcoder_api/persistence/database.py # optional: reuse for metadata engine (no change needed)
backend/pyproject.toml                            # add deps: argon2-cffi, webauthn, cryptography
```

### Modified files (frontend)

```
frontend/src/lib/config.ts            # add SERVER_MODE, VITE_SERVER_BASE, VITE_RP_ID
frontend/src/lib/api/transport.ts     # inject Authorization + X-Project-Id headers
frontend/src/lib/api/endpoints.ts     # add auth/server/project/sync endpoints
frontend/src/stores/project.ts        # server-mode open/close via project_id (not path)
frontend/src/App.tsx                  # server-mode login gate + project picker
```

### Documentation (must stay in sync per AGENTS.md)

```
backend/src/qualcoder_api/help_docs/*.md   # add a "Server" help topic (mirror to docs/*.md)
docs/SERVER_PLAN.md                        # this file
docs/SERVER_OPERATIONS.md                  # operator runbook (backup/restore/cloud) — Phase 4/5
frontend/tests-e2e/COVERAGE.md             # add server-mode rows (Phase 11)
```

---

## 4. Configuration (`core/server_config.py`)

Single module, all values read from env with safe defaults. No other module may
read these env vars directly.

| Env var | Default | Meaning |
|---------|---------|---------|
| `QC_SERVER_MODE` | `false` | Enables server features (auth, sessions, registry, sync hub) |
| `QC_DATA_DIR` | `./data` | Root for projects/uploads/temp/backups/metadata/logs |
| `QC_METADATA_DB` | `<QC_DATA_DIR>/metadata/qualcoder.db` | Metadata SQLite path |
| `QC_SECRET_KEY` | (required in server mode) | Used for token/challenge derivation |
| `QC_TOKEN_TTL_SECS` | `604800` (7d) | Opaque token lifetime |
| `QC_PASSWORD_ALGO` | `argon2` | `argon2` (default) or `bcrypt` |
| `QC_RP_ID` | (required for passkey) | WebAuthn relying-party id (hostname, no scheme) |
| `QC_RP_ORIGIN` | `https://<RP_ID>` | WebAuthn expected origin |
| `QC_CORS_ORIGINS` | (empty) | Extra allowed origins (comma-separated) |
| `QC_SESSION_IDLE_SECS` | `900` | Close idle project sessions after this |
| `QC_MAX_UPLOAD_BYTES` | `2147483648` (2 GiB) | Upload size cap |
| `QC_BACKUP_RETENTION` | `daily=14,weekly=8,monthly=12` | Retention policy |
| `QC_RCLONE_CONF` | `/etc/rclone/rclone.conf` | rclone config path (cloud backup) |
| `QC_RCLONE_REMOTE` | `qcnext-crypt:` | rclone crypt remote name |

Rules:

- `QC_SECRET_KEY` **required** when `QC_SERVER_MODE` is true — fail fast at
  startup if missing (clear error message).
- Every path helper resolves against `QC_DATA_DIR` and refuses `..` escapes.

---

## 5. Phase 0 — Infrastructure scaffolding (zero behavior change)

**Goal:** establish the mode flag, config, and startup gating so all later
phases are additive and the local app is provably untouched.

### 5.1 `core/server_config.py`
- `is_server_mode() -> bool` (read `QC_SERVER_MODE`).
- Dataclass `ServerConfig` with all fields from Section 4, loaded once.
- `path_helpers`: `projects_root()`, `uploads_dir()`, `temp_dir()`,
  `backups_dir()`, `metadata_db_path()`, `logs_dir()`, and
  `project_dir(project_id)`, `resolve_under_root(name) -> Path` (rejects `..`,
  absolute paths, and symlinks).

### 5.2 `main.py`
- In `create_app()`, read `is_server_mode()`.
- If OFF: exactly current behavior (do not change the existing code path).
- If ON: skip the `_sync_loop`/`_presence_loop` singleton tasks; register the
  server routers (added in later phases); add a startup check that
  `QC_SECRET_KEY` is set.
- Keep `service = ProjectService()` (used only in local mode).

### 5.3 `api/v1/deps.py`
- Extract the current `get_service()` body; add a ContextVar import and read it
  first (see Phase 2 for the actual variable). In Phase 0, define the ContextVar
  `CURRENT_SERVICE` here but leave it unset, and make `get_service()` fall back
  to the global singleton — so behavior is unchanged until Phase 2.

### Acceptance
- `pytest` (994 tests) green with `QC_SERVER_MODE` unset.
- `QC_SERVER_MODE=true` without `QC_SECRET_KEY` → app refuses to start with a
  clear message (tested in `test_server_config.py`).
- No behavioral change to the desktop app.

---

## 6. Phase 1 — Metadata DB, opaque tokens, passkeys

**Goal:** user accounts, login (password + passkey), and token validation.
Purely additive; the local app does not use any of it.

### 6.1 Metadata DB (`persistence/metadata_schema.py` + `metadata_db.py`)

`metadata_db.py`:
- `metadata_engine()` — `sqlite+aiosqlite` engine for `QC_METADATA_DB` (WAL,
  `busy_timeout=5000`, `foreign_keys=ON`).
- `metadata_factory()` — session maker.
- `migrate_metadata()` — run ordered migrations from `metadata_schema.py`,
  tracking version in a `schema_version(version INTEGER)` table. Called once at
  startup (server mode only).

DDL (exact tables — implement literally):

```sql
CREATE TABLE users (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL DEFAULT '',
  email       TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL DEFAULT '',   -- argon2 (or bcrypt); '' = passwordless
  role        TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
  disabled    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE passkeys (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  credential_id TEXT NOT NULL UNIQUE,
  public_key   TEXT NOT NULL,               -- PEM/SPKI
  sign_count   INTEGER NOT NULL DEFAULT 0,
  transports   TEXT NOT NULL DEFAULT '',
  name         TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL
);

CREATE TABLE auth_tokens (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL UNIQUE,         -- sha256 hex of the raw token
  name        TEXT NOT NULL DEFAULT '',
  expires_at  TEXT NOT NULL,
  revoked     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  last_used_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE projects (
  id          TEXT PRIMARY KEY,             -- uuid4 hex
  name        TEXT NOT NULL,
  owner_id    INTEGER NOT NULL REFERENCES users(id),
  data_path   TEXT NOT NULL,                -- absolute path under QC_DATA_DIR
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleting')),
  size_bytes  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE project_members (
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('owner','editor','viewer')),
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE backup_records (
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

CREATE TABLE server_audit (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER,                       -- NULL = system
  project_id  TEXT,
  action      TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);

CREATE TABLE webauthn_challenges (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  challenge   TEXT NOT NULL UNIQUE,          -- base64url challenge
  user_id     INTEGER,                       -- NULL for login-begin
  kind        TEXT NOT NULL CHECK (kind IN ('register','login')),
  expires_at  TEXT NOT NULL
);
```

### 6.2 Passwords (`services/password.py`)
- `hash_password(pw) -> str` and `verify_password(pw, stored) -> bool` using
  `argon2-cffi` (fall back to `bcrypt` if `QC_PASSWORD_ALGO=bcrypt`).
- Verify is constant-time; reject empty password on register (unless passkey is
  provided).

### 6.3 Opaque tokens (`services/token_service.py`)
- `issue_token(user_id, name) -> raw_token`:
  - `raw = secrets.token_urlsafe(32)`.
  - Store only `hashlib.sha256(raw).hexdigest()` in `auth_tokens` with
    `expires_at = now + QC_TOKEN_TTL_SECS`.
  - Return the **raw** token exactly once.
- `verify_token(raw) -> user_id | None`:
  - Hash, look up, reject if revoked/expired/disabled user; update `last_used_at`.
  - Prune expired/revoked rows lazily (DELETE WHERE expires_at < now).
- `revoke_token(raw)`, `revoke_all_for_user(user_id)`.
- Never log the raw token.

### 6.4 Passkeys (`services/passkey_service.py`) — `webauthn` library

Use the `webauthn` PyPI package (WebAuthn/FIDO2 server-side) and its
`generate_registration_options` / `verify_registration_response` /
`generate_authentication_options` / `verify_authentication_response` helpers.

- `begin_registration(user)` → returns `PublicKeyCredentialCreationOptions`
  (JSON) and stores the challenge in `webauthn_challenges` (kind=register,
  TTL 300s). `rp_id=QC_RP_ID`, `rp_name="QualCoder"`, `origin=QC_RP_ORIGIN`.
- `complete_registration(user, attestation)` → verify; on success insert a row
  into `passkeys` (credential_id, public_key, sign_count, transports, name).
- `begin_login(username)` → challenge (kind=login, TTL 300s); include the
  user's passkeys as `allowCredentials` when the user exists.
- `complete_login(username, assertion)` → verify; update `sign_count`; return
  the user (caller issues a token).
- Store challenges in DB (not in-memory) so a restart doesn't lose in-flight
  registrations.

### 6.5 Auth endpoints (`api/v1/auth.py`)

All JSON. Register under prefix `/auth`.

| Method | Path | Body/params | Returns | Notes |
|---|---|---|---|---|
| POST | `/auth/login` | `{username, password}` | `{token, expires_at, user}` | 401 on bad creds/disabled |
| POST | `/auth/register` | `{username, display_name?, email?, password?}` | `{user}` | Admin-only by default (see 6.6) |
| POST | `/auth/passkey/register/begin` | — (auth) | WebAuthn options | must be logged in |
| POST | `/auth/passkey/register/complete` | attestation JSON | `{ok}` | must be logged in |
| POST | `/auth/passkey/login/begin` | `{username}` | options | public |
| POST | `/auth/passkey/login/complete` | `{username, assertion}` | `{token, expires_at, user}` | public |
| POST | `/auth/logout` | — (auth) | `{ok}` | revokes the presented token |
| POST | `/auth/refresh` | — (auth) | `{token, expires_at}` | revoke old, issue new |
| GET  | `/auth/me` | — (auth) | `{user}` | current user |
| GET  | `/auth/passkeys` | — (auth) | `[{id,name,created_at}]` | own passkeys |
| DELETE | `/auth/passkeys/{id}` | — (auth) | `{ok}` | own passkey |

### 6.6 `api/v1/auth_deps.py`
- `get_current_user(authorization: Header) -> UserRow`:
  - Parse `Authorization: Bearer <token>`; 401 if missing/malformed.
  - `token_service.verify_token` → user; 401 if none/disabled.
- `require_admin(user)` → 403 if role != 'admin'.
- `current_user_dep = Depends(get_current_user)` for reuse.
- Registration gating: `POST /auth/register` is 403 unless (a) the caller is an
  admin, or (b) the `users` table is empty (bootstrap: the first registered
  user becomes admin). Document this clearly.

### 6.7 Frontend (Phase 1 subset)
- `frontend/src/lib/session.ts`: `setToken/clearToken/getToken`, using Tauri
  secure-store when in Tauri shell, else `localStorage`; `setProjectId/getProjectId`.
- `frontend/src/features/auth/LoginScreen.tsx`: username+password, plus a
  "Sign in with passkey" button (uses `@simplewebauthn/browser` `startAuthentication`).
- `frontend/src/features/auth/RegisterPasskey.tsx`: after login, register a
  passkey (`startRegistration`).

### Acceptance
- Password login returns a working token; `GET /auth/me` returns the user.
- Wrong password → 401; disabled user → 401; logout revokes (reuse → 401).
- Register/authenticate a passkey end-to-end (test with a software authenticator
  via the `webauthn` library's test helpers).
- Metadata DB created on first boot; migrations idempotent (run twice).
- Existing 994 tests still green (server mode off).

---

## 7. Phase 2 — Session pool, project registry, ACL, upload/download

**Goal:** the server becomes multi-tenant: multiple projects open at once,
owned/ACL-gated, uploadable/downloadable. The local app is still unchanged.

### 7.1 Session manager (`services/session_manager.py`)

- `CURRENT_SERVICE: ContextVar[ProjectService | None]` (imported by `deps.py`).
- `class SessionEntry`: holds a `ProjectService` instance, `last_used` timestamp,
  and an `asyncio.Lock` (per project — enforces single-writer *within* the
  process).
- `class SessionManager` (module singleton `manager`):
  - `sessions: dict[str, SessionEntry]` keyed by `project_id`.
  - `async acquire(user_id, project_id, role) -> ProjectService`:
    1. Load project row + member role from metadata; 404 if unknown, 403 if no
       membership.
    2. Enforce coder-name==username: the `codername` passed to
       `ProjectService.open_project` is `user.username` (decision 5). No other
       value is ever accepted.
    3. Under the per-project lock: if session exists, return it; else create a
       `ProjectService`, call `open_project(data_path, codername=username)`.
    4. Update `last_used`.
  - `async release_all_idle()`: close sessions idle > `QC_SESSION_IDLE_SECS`
    (calls `ProjectService.close_project()` which checkpoints WAL). Run by the
    lifespan loop every 60s.
  - `async close(project_id)` (used on project delete).
- **Single-writer guard:** `ProjectService.open_project` writes a `server.lock`
  file in the project dir. At startup, `SessionManager` refuses to open any
  project whose `server.lock` is held by another live PID (mirrors existing
  lock logic). This is what makes "one writer" concrete.

### 7.2 Request routing (`api/v1/deps.py` + `auth_deps.py`)

- New dependency `resolve_project_service(x_project_id: Header = Header(...))`:
  1. `get_current_user`.
  2. `manager.acquire(user.id, x_project_id, role)`.
  3. `CURRENT_SERVICE.set(service)`; yield; reset token in `finally`.
- Change `deps.get_service()`:
  - If `CURRENT_SERVICE.get()` is set → return it (server mode).
  - Else → return the global `main.service` (local mode). Unchanged otherwise.

### 7.3 Wire the existing routers (`api/v1/router.py`)

- In server mode, build the project-scoped routers with
  `dependencies=[Depends(resolve_project_service)]` so every existing endpoint
  (sources, codes, codings, reports, …) is auth + project gated **without
  touching the endpoint functions**.
- The local project-lifecycle endpoints (`POST /projects`,
  `POST /projects/open`, `POST /projects/close`, `POST /projects/compact`) are
  **disabled in server mode** (return 410 with a message "managed by the server
  project API"). They must remain fully functional in local mode.
- Register the new server routers (Section 7.4) in server mode only.

### 7.4 Server project registry (`api/v1/server_projects.py`)

| Method | Path | Body/params | Returns | Permissions |
|---|---|---|---|---|
| GET | `/server/projects` | — | `[{id,name,role,updated_at,owner}]` | any (filtered to own memberships) |
| POST | `/server/projects` | `{name}` | `{id,name}` | any authenticated user (becomes owner) |
| GET | `/server/projects/{id}` | — | project detail + role | member |
| DELETE | `/server/projects/{id}` | — | `{ok}` | owner or admin |
| GET | `/server/projects/{id}/members` | — | `[{user_id,username,role}]` | owner/admin |
| PUT | `/server/projects/{id}/members/{user_id}` | `{role}` | `{ok}` | owner/admin |
| DELETE | `/server/projects/{id}/members/{user_id}` | — | `{ok}` | owner/admin |
| POST | `/server/projects/{id}/open` | — | `{ok}` (session warm-up) | member |
| POST | `/server/projects/{id}/close` | — | `{ok}` | member |

Behavior notes:
- `POST /server/projects` creates the project via `ProjectService.create_project`
  under `projects_root()/<uuid>/<name>.qda`, inserts `projects` +
  `project_members(owner)`, returns the id. `codername` = creator username.
- The client then uses **`X-Project-Id: <id>`** on every project-scoped request
  (not a path). `data_path` is stored; clients never see or send it.
- Deleting a project: set `status='deleting'`, close session, remove the
  directory, delete rows (cascade), then delete the `projects` row.

### 7.5 ACL enforcement

- Viewer: all mutating HTTP methods (POST/PUT/PATCH/DELETE) to project-scoped
  routes are rejected with 403, except explicitly allowed read-only GETs. Add a
  helper `require_editor(user, role)` in `auth_deps.py` and apply it to mutating
  routes via a second router dependency, or by checking method in
  `resolve_project_service` (simpler: enforce in the dependency — block non-GET
  when role == 'viewer').
- Owner/editor: full access. Admin: treated as owner on any project.

### 7.6 Upload / download

- **Download** `GET /server/projects/{id}/download?include_backups=0`:
  - Checkpoint WAL (existing `cleanup_service.checkpoint`), then
    `shutil.make_archive` of the project dir into `temp_dir/`, **excluding**
    `changes/`, `presence/`, `server.lock`, `project_in_use.lock`, and
    `backups/` unless `include_backups=1`. Return as streaming
    `FileResponse` with `Content-Disposition: attachment; filename="<name>.zip"`.
  - Member (any role) may download.
- **Upload** `POST /server/projects/upload` (multipart `file`):
  - Save to `uploads_dir/<uuid>.zip`; enforce `QC_MAX_UPLOAD_BYTES`.
  - Validate: contains `data.qda`; `data.qda` passes the existing
    "is a QualCoder database" check (reuse `open_project` header check or
    `merge_projects` validation logic).
  - Extract safely (zip-slip protection: reject absolute paths and `..`; reject
    symlinks); wrap into `projects_root()/<uuid>/<name>.qda/`; register owner.
  - On any failure, clean up the staging dir and return 422 with the reason.
- **Import-from-disk** `POST /server/projects/import` `{source_path}` (admin
  only): copy an existing `.qda` folder already on the server host into the
  managed root. Optional but useful for migration.

### 7.7 `services/project_service.py` changes
- Add `server.lock` write/remove around open/close (guarded by server mode; no
  effect locally).
- Add a hook so that, in server mode, `codername` is forced to the
  authenticated username (or assert it and 400 otherwise).

### 7.8 Frontend (Phase 2 subset)
- `features/server/ProjectsList.tsx`: list/create/delete/share projects.
- `features/server/ShareDialog.tsx`: manage members + roles.
- Upload/download buttons wired to the endpoints above.
- `stores/project.ts`: in server mode, `openProject` takes `projectId` (sets the
  `X-Project-Id` header + calls `POST /server/projects/{id}/open`); `closeProject`
  posts `/server/projects/{id}/close`.

### Acceptance
- Two users can hold two different projects open at once (sessions independent).
- A user with no membership → 403; viewer → can GET but not POST; editor can
  mutate; owner can share/delete.
- Upload a desktop `.qda` zip → appears in list → download returns a valid,
  re-openable project.
- Coder name in every created row equals the username (verify in DB).
- Existing 994 tests green with server mode off.

---

## 8. Phase 3 — Server collaboration (sync hub)

**Goal:** replace shared-folder sidecar sync with server-mediated sync. Reuse
`sync_engine` replay/conflict logic unchanged; change transport only.

### 8.1 Design

- The server session holds the **canonical** project DB. Only the server writes it.
- Each client keeps a stable `instance_id` (reuse `user_settings.get_instance_id`
  logic, but in server mode derive it from the token/username so it is stable
  per account, not per machine).
- Server-side per-client sidecars live under
  `projects/<id>/<name>.qda/changes/<instance_id>/changes.jsonl` (server-side
  storage, not a shared folder).

### 8.2 Transport indirection (`sync_engine.py`)
- Introduce a `SyncTransport` protocol with two async methods:
  - `push(project_id, instance_id, entries: list[dict]) -> dict`
  - `pull(project_id, instance_id, since: int) -> list[dict]`
- Default implementation = current file behavior (read/write the shared
  `changes/` folder) — **unchanged** for local mode.
- Server implementation = HTTP client calling the hub endpoints below. Selected
  when server mode is on. `run_sync_cycle` and `export_pending`/`import_pending`
  call the transport instead of the filesystem directly. **Replay, natural-key
  matching, and conflict recording are not modified.**

### 8.3 Sync hub endpoints (`api/v1/server_sync.py`)

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| POST | `/sync/push` | `{entries: [...]}` | `{applied, conflicts, retries}` | X-Project-Id required |
| GET | `/sync/pull` | `?since=<int>` | `{entries: [...], server_seq: int}` | X-Project-Id required |
| POST | `/sync/presence` | `{file_id?, file_name?}` | `{ok}` | heartbeat |
| GET | `/sync/state` | — | `{server_seq, members_present, conflicts}` | sync status |

- `push`: server appends the client's entries to its server-side sidecar, then
  replays them into the canonical DB using the existing `import_pending`-style
  replay (`_replay_one`), returning applied/conflicts/retries exactly as the
  engine reports them.
- `pull`: server returns every *other* client's sidecar entries with
  `seq > since`, ordered by seq, so the client can replay locally via the
  existing import path.
- `presence`: updates a server-side presence record (replace the `presence/`
  folder heartbeat); `GET /projects/openers` reads it (endpoint already exists).

### 8.4 Client-side changes (local app running against the server)

- `sync.sync_enabled()` returns `True` in server mode (server is authoritative).
- `sync.detect_shared` / `auto_enable_decision` return `shared=True` in server
  mode (so the existing auto-enable flow still fires).
- The background `_sync_loop` (local app) calls `transport.push/pull` instead of
  folder I/O when the app is pointed at a server (detected from the resolved
  API base). When pointed at the embedded local backend, behavior is unchanged.

### 8.5 Conflict resolution

- Conflicts surfaced by the server during `push` are returned to the client and
  displayed via the existing conflict UI. The existing `resolve_conflict`
  endpoint/props stay; resolution is pushed back via `push` (a new sync entry).

### Acceptance
- Two accounts edit the same project against the server; changes propagate via
  push/pull within one sync cycle; concurrent edits produce a conflict in the
  existing `sync_conflict` table; resolution converges both clients.
- Local shared-folder sync still works when server mode is off (existing sync
  tests unchanged).
- Presence shows live collaborators (no `presence/` folder required).

---

## 9. Phase 4 — Backups (local + rclone → Nextcloud)

**Goal:** consistent, scheduled, restorable backups mirrored to Nextcloud with
client-side encryption.

### 9.1 `services/backup_service.py`
- `create_backup(project_id, kind) -> backup_record`:
  1. Checkpoint WAL (`cleanup_service.checkpoint`).
  2. `shutil.make_archive(backups_dir()/local/<project_id>/<name>_<ts>, 'gztar',
     project_dir)` excluding `changes/`, `presence/`, locks, `backups/`.
  3. Compute sha256 of the archive; write a `backup_records` row
     (`cloud_status='pending'`).
- `restore_backup(project_id, backup_id)`: extract archive to a temp dir, verify
  checksum, swap into place (close session first), reopen. Restore creates a
  new `project_id` optionally (never clobber live data by default).
- `apply_retention()`: parse `QC_BACKUP_RETENTION`, delete expired archives and
  their rows (mark cloud objects for deletion).

### 9.2 `services/backup_scheduler.py`
- Asyncio task: daily/weekly/monthly schedule via the retention policy; also a
  `trigger_backup(project_id, kind='manual')` for on-demand.
- Idempotent; catches and logs failures; writes `server_audit` rows.

### 9.3 Backup endpoints (`api/v1/server_backups.py`)

| Method | Path | Returns | Permissions |
|---|---|---|---|
| GET | `/server/projects/{id}/backups` | `[{id,kind,size_bytes,checksum,cloud_status,created_at}]` | owner/admin |
| POST | `/server/projects/{id}/backups` | `{backup}` (triggers manual) | owner/admin |
| POST | `/server/projects/{id}/backups/{backup_id}/restore` | `{new_project_id}` | owner/admin |
| POST | `/admin/backup/run-all` | `{ok, ran}` | admin |
| GET | `/admin/backup/status` | aggregate status | admin |

### 9.4 Cloud mirror (rclone → Nextcloud)

- `scripts/rclone.conf.template`: two remotes:
  - `nextcloud` = WebDAV remote pointing at the Nextcloud instance
    (`type=webdav`, `url`, `user`, `pass` filled from env/secrets).
  - `qcnext-crypt` = `crypt` remote wrapping `nextcloud:qualcoder-backups`
    (`password`/`password2` from env).
- `scripts/cloud-backup.sh` (run as a sidecar/cron):
  1. `rclone sync <backups_dir>/local nextcloud-crypt:` (with `--checksum`).
  2. On success mark `backup_records.cloud_status='uploaded'` for the files
     uploaded (match by filename); on failure `'failed'`.
  3. Periodic `rclone check` + a monthly test restore to a scratch bucket.
- Credentials come from env, never baked into the image.

### Acceptance
- Manual backup produces a restorable archive; restore into a new project id
  opens and matches the source data.
- Retention prunes correctly.
- rclone sync uploads to Nextcloud; `cloud_status` transitions correctly; a
  restored object decrypts and opens.

---

## 10. Phase 5 — Docker packaging

### 10.1 `backend/Dockerfile` (multi-stage)
- Base `python:3.11-slim`.
- Install system deps for the heavy libs (build tools for `faster-whisper`,
  `pyreadstat`, etc.) in a builder stage; final stage installs wheels + `rclone`.
- Create non-root user `qualcoder` (uid 1000); `WORKDIR /app`;
  copy backend, `pip install .` (the package), copy scripts.
- `EXPOSE 8765`; `HEALTHCHECK` on `/api/v1/health`.
- `CMD ["/app/scripts/docker-entrypoint.sh"]`.

### 10.2 `backend/docker-compose.yml`
- `qualcoder`: builds the image; env from `.env`; volumes `data:/data/qualcoder`
  and `logs:/var/log/qualcoder`; depends on nothing (metadata is SQLite).
- `caddy` (optional, enabled by default): reverse proxy + automatic TLS;
  serves the built frontend static files and proxies `/api` to `qualcoder`.
- `cloud-backup` (optional): runs `cloud-backup.sh` on a cron; shares the
  `data` volume; holds rclone config from a secret/volume.
- `docker-compose.override.yml` for local dev (no TLS, hot reload).

### 10.3 `scripts/docker-entrypoint.sh`
1. Fail if `QC_SERVER_MODE=true` and `QC_SECRET_KEY` missing.
2. Run `metadata` migrations (`cli.py migrate`).
3. `cli.py bootstrap-admin` (create admin from `QC_ADMIN_USER`/`QC_ADMIN_PASS`
   if provided and no users exist).
4. Start uvicorn (`qualcoder_api.main:app`).

### 10.4 `cli.py`
- Subcommands: `migrate`, `bootstrap-admin`, `backup`, `restore`, `apply-retention`.
- Reuses `backup_service` / `metadata_db`; lets cron and operators drive the
  same code the app uses.

### Acceptance
- `docker compose up` boots; `/api/v1/health` returns ok; login works; a project
  can be created, uploaded, edited, downloaded, backed up, and restored.
- Container runs as non-root; restart is clean (no data loss; sessions reopen).

---

## 11. Testing & CI

### 11.1 Backend (pytest)
- Keep all 994 existing tests green with `QC_SERVER_MODE` unset.
- New suites (each file named in Section 3): config, metadata DB/migrations,
  token service, password, passkey (use the `webauthn` library's in-memory
  authenticator helper), session manager, auth API, server projects/ACL,
  upload/download, backups, server sync, admin.
- Run: `backend/.venv/Scripts/python.exe -m pytest tests` plus
  `-m ruff check src` and `-m mypy src` (per AGENTS.md).

### 11.2 Frontend
- `npm test` (vitest): auth client, session storage, project store server mode.
- `npx tsc --noEmit`, `npx eslint src --max-warnings 0`.
- Playwright e2e: new server-mode specs (login, create project, upload, edit,
  download, share). Update `frontend/tests-e2e/COVERAGE.md`. Run from a clean
  state per AGENTS.md (kill stale processes, clear `%TEMP%\qc-e2e`).

### 11.3 Server smoke test script
- `backend/scripts/smoke-test.sh`: boots the container, hits health, registers
  admin, creates project, uploads a fixture zip, downloads it, backs it up,
  restores it. Fails on any non-2xx.

---

## 12. Rollout / migration order (safe path)

1. Phase 0 (scaffolding) — invisible, safe to merge.
2. Phase 1 (auth) — additive; ship behind `QC_SERVER_MODE`.
3. Phase 2 (sessions + registry + upload/download) — server-only; local app
   unaffected because server routers are only registered in server mode.
4. Phase 3 (sync hub) — highest risk; ship behind server mode and keep the
   shared-folder path intact for local mode; add feature-flag
   `QC_SERVER_SYNC` to toggle hub vs folder-sync if a regression appears.
5. Phase 4 (backups) — additive.
6. Phase 5 (Docker) — packaging only; no logic change.

Each phase is independently mergeable and reversible. Do **not** combine phases
in a single change; each phase must pass its own acceptance checklist plus the
"local app unchanged" invariant before the next begins.

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `ProjectService` is a singleton with mutable state reused across sessions | Wrap per-project state in `SessionEntry`; never share a `ProjectService` across projects |
| Two writers corrupt a SQLite project | Per-project `asyncio.Lock` + `server.lock`; reject horizontal scaling at startup |
| Auth token leaks | Store only sha256 hashes; short TTL; revoke on logout; never log tokens |
| Passkey verification subtleties (origin/rp_id/signCount) | Pin `webauthn` version; cover with in-memory authenticator tests |
| Sync hub regression breaks local collaboration | Transport indirection only; folder path untouched; `QC_SERVER_SYNC` flag |
| Upload zip-slip / huge files | Quarantine to `uploads/`, validate, size cap, path sanitization, no symlinks |
| Backup inconsistency (WAL) | Always `checkpoint` before archive; verify checksum on restore |
| rclone config/creds leakage | Secrets via env/secret volumes; `.env` git-ignored |

---

## 14. End-to-end acceptance checklist (final sign-off)

- [ ] Desktop app (server mode OFF) unchanged: all 994 backend tests + 336
      vitest + 53 e2e pass.
- [ ] Server boots in Docker as non-root; health OK.
- [ ] Admin bootstrap; password login; passkey registration + login work.
- [ ] Two users, two projects open simultaneously; ACL (viewer/editor/owner)
      enforced; coder name == username everywhere.
- [ ] Upload a real `.qda` (e.g. the LSTeach2.0 backup) → opens → edit → download
      → re-opens correctly.
- [ ] Collaboration: two accounts converge on the same project; conflicts
      surface and resolve; presence shows live users.
- [ ] Backup: manual + scheduled snapshots; retention prunes; restore into a new
      project id works.
- [ ] Cloud: rclone syncs to Nextcloud (crypt); a restored object decrypts and
      opens; monthly test-restore documented.
- [ ] Local feature development flows to server automatically (add a dummy
      `services/` feature; confirm it appears on the server with no server-side
      code change).
