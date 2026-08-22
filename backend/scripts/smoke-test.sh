#!/usr/bin/env bash
# End-to-end server smoke test (SERVER_PLAN.md §11.3).
#
# Boots nothing itself — run against a LIVE stack (compose up):
#   BASE=http://localhost:8765 ADMIN_USER=admin ADMIN_PASS=... ./smoke-test.sh
#
# Exercises: health → login → create project → upload zip → edit via API →
# download → backup → restore → delete. Fails on any non-2xx.
set -euo pipefail

BASE="${BASE:-http://localhost:8765}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

command -v curl >/dev/null || fail "curl required"
[ -n "$ADMIN_PASS" ] || fail "ADMIN_PASS required"

echo "[1/9] health"
curl -fsS "$BASE/api/v1/health" >/dev/null || fail "health"

echo "[2/9] login"
LOGIN=$(curl -fsS -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}") || fail "login"
TOKEN=$(echo "$LOGIN" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
AUTH="Authorization: Bearer $TOKEN"

echo "[3/9] register passkey-capable config check (me endpoint)"
curl -fsS "$BASE/api/v1/auth/me" -H "$AUTH" >/dev/null || fail "me"

echo "[4/9] upload project zip"
STAGE="$WORK/Fixture.qda"
mkdir -p "$STAGE/documents"
python - "$STAGE" <<'PY'
import sqlite3, sys, pathlib
root = pathlib.Path(sys.argv[1])
conn = sqlite3.connect(root / "data.qda")
conn.executescript("""
CREATE TABLE IF NOT EXISTS about (about TEXT);
INSERT INTO about VALUES ('QualCoder 4.0');
CREATE TABLE IF NOT EXISTS code_name (cid INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, memo TEXT, catid INTEGER, owner TEXT, date TEXT, color TEXT, supercid INTEGER, memo_type TEXT DEFAULT '', position INTEGER DEFAULT 0);
INSERT INTO code_name (name, owner, date) VALUES ('SmokeCode', 'smoke', '2026-01-01');
""")
conn.commit(); conn.close()
(root / "documents" / "note.txt").write_text("hello", encoding="utf-8")
PY
python -c "import shutil; shutil.make_archive(r'$WORK/fixture', 'zip', r'$STAGE')"
mv "$WORK/fixture.zip" "$WORK/fixture.zip" 2>/dev/null || true
UP=$(curl -fsS -X POST "$BASE/api/v1/server/projects/upload" \
  -H "$AUTH" -F "file=@$WORK/fixture.zip") || fail "upload"
PID=$(echo "$UP" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "    project id: $PID"

echo "[5/9] open session + append data through the project API"
curl -fsS -X POST "$BASE/api/v1/server/projects/$PID/open" -H "$AUTH" >/dev/null || fail "open"
curl -fsS -X POST "$BASE/api/v1/codes" -H "$AUTH" -H "X-Project-Id: $PID" \
  -H 'Content-Type: application/json' \
  -d '{"name":"SecondCode","owner":"smoke"}' >/dev/null || fail "append"

echo "[6/9] download round trip contains both codes"
DL="$WORK/download.zip"
curl -fsS "$BASE/api/v1/server/projects/$PID/download" -H "$AUTH" -o "$DL" || fail "download"
python - "$DL" <<'PY' || fail "download content"
import sqlite3, sys, zipfile, tempfile, pathlib
zf = zipfile.ZipFile(sys.argv[1])
tmp = pathlib.Path(tempfile.mkdtemp())
zf.extractall(tmp)
db = sqlite3.connect(tmp / "data.qda")
names = [r[0] for r in db.execute("SELECT name FROM code_name")]
assert "SmokeCode" in names and "SecondCode" in names, names
PY

echo "[7/9] manual backup"
BK=$(curl -fsS -X POST "$BASE/api/v1/server/projects/$PID/backups" -H "$AUTH") || fail "backup"
BID=$(echo "$BK" | python -c "import sys,json;print(json.load(sys.stdin)['backup']['id'])")

echo "[8/9] restore from backup"
curl -fsS -X POST "$BASE/api/v1/server/projects/$PID/backups/$BID/restore" \
  -H "$AUTH" >/dev/null || fail "restore"

echo "[9/9] cleanup project"
curl -fsS -X DELETE "$BASE/api/v1/server/projects/$PID" -H "$AUTH" >/dev/null || fail "delete"

echo "SMOKE OK"
