#!/usr/bin/env bash
# QualCoder server entrypoint (SERVER_PLAN.md §10.3).
set -euo pipefail

: "${QC_SERVER_MODE:=true}"
export QC_SERVER_MODE

if [ "${QC_SERVER_MODE}" != "true" ]; then
  echo "docker entrypoint expects QC_SERVER_MODE=true (local desktop builds embed the backend instead)" >&2
  exit 2
fi

if [ -z "${QC_SECRET_KEY:-}" ]; then
  echo "QC_SECRET_KEY is required. Generate one with:" >&2
  echo "  python -m qualcoder_api.cli secret" >&2
  exit 2
fi

echo "[entrypoint] applying metadata migrations ..."
python -m qualcoder_api.cli migrate

echo "[entrypoint] bootstrapping admin (skipped when users exist) ..."
python -m qualcoder_api.cli bootstrap-admin || true

echo "[entrypoint] starting uvicorn on :8765"
exec uvicorn qualcoder_api.main:app --host 0.0.0.0 --port 8765 --workers 1
