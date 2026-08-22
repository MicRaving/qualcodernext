"""Server management CLI (SERVER_PLAN.md §10.4).

Subcommands used by the Docker entrypoint and operators:

    python -m qualcoder_api.cli migrate
    python -m qualcoder_api.cli bootstrap-admin [--username U] [--password P]
    python -m qualcoder_api.cli check-config

``backup`` / ``restore`` / ``apply-retention`` arrive with Phase 4
(backup_service) and are intentionally absent until then.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys


def _require_server_mode() -> None:
    os.environ.setdefault("QC_SERVER_MODE", "true")
    from qualcoder_api.core.server_config import (
        ServerConfigError,
        is_server_mode,
        load_server_config,
        validate_server_config,
    )

    if not is_server_mode():
        print("QC_SERVER_MODE is not enabled — nothing to manage.", file=sys.stderr)
        raise SystemExit(2)
    try:
        validate_server_config(load_server_config())
    except ServerConfigError as err:
        print(f"configuration error: {err}", file=sys.stderr)
        raise SystemExit(2) from err


async def _cmd_migrate() -> int:
    from qualcoder_api.persistence import metadata_db

    version = await metadata_db.migrate_metadata(_metadata_path())
    print(f"metadata schema at version {version}")
    return 0


def _metadata_path():
    from qualcoder_api.core.server_config import load_server_config

    return load_server_config().metadata_db


async def _cmd_bootstrap_admin(username: str | None, password: str | None) -> int:
    from qualcoder_api.persistence import metadata_db
    from qualcoder_api.services.password import hash_password

    if await metadata_db.count_users() > 0:
        print("users already exist — bootstrap skipped")
        return 0
    username = username or os.environ.get("QC_ADMIN_USER", "")
    password = password or os.environ.get("QC_ADMIN_PASS", "")
    if not username or not password:
        print(
            "bootstrap-admin requires --username/--password or QC_ADMIN_USER/QC_ADMIN_PASS",
            file=sys.stderr,
        )
        return 2
    user = await metadata_db.insert_user(
        username, hash_password(password), role="admin"
    )
    print(f"admin created: {user['username']} (id {user['id']})")
    return 0


def _cmd_check_config() -> int:
    from qualcoder_api.core.server_config import load_server_config

    cfg = load_server_config()
    print(f"data_dir        = {cfg.data_dir}")
    print(f"metadata_db     = {cfg.metadata_db}")
    print(f"token_ttl_secs  = {cfg.token_ttl_secs}")
    print(f"rp_id           = {cfg.rp_id or '(passkeys disabled)'}")
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qualcoder-server")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply metadata DB migrations")
    boot = sub.add_parser("bootstrap-admin", help="create the first admin account")
    boot.add_argument("--username", default=None)
    boot.add_argument("--password", default=None)
    sub.add_parser("check-config", help="print resolved server configuration")
    sub.add_parser("secret", help="print a fresh QC_SECRET_KEY candidate")

    args = parser.parse_args(argv)
    if args.command == "secret":
        print(secrets.token_urlsafe(48))
        return 0

    _require_server_mode()

    if args.command == "migrate":
        return asyncio.run(_cmd_migrate())
    if args.command == "bootstrap-admin":
        return asyncio.run(_cmd_bootstrap_admin(args.username, args.password))
    if args.command == "check-config":
        return _cmd_check_config()
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
