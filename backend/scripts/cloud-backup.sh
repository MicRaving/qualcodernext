#!/usr/bin/env bash
# Cloud backup mirror (SERVER_PLAN.md §9.4) — run on a schedule (compose
# `cloud-backup` profile or host cron). Uploads local snapshots to the
# rclone crypt remote and marks cloud_status in the metadata DB.
set -euo pipefail

REMOTE="${RCLONE_REMOTE:-qcnext-crypt:}"
BACKUPS="/data/qualcoder/backups/local"
export RCLONE_CONFIG="${RCLONE_CONFIG:-/config/rclone/rclone.conf}"

if [ ! -f "$RCLONE_CONFIG" ]; then
  echo "cloud-backup: no rclone config at $RCLONE_CONFIG — skipping" >&2
  exit 0
fi

rclone sync "$BACKUPS" "$REMOTE" --checksum
echo "cloud-backup: mirror complete"
