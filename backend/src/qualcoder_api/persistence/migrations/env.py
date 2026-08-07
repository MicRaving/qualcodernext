"""Alembic environment — sync engine for project databases.

Migrations run with a plain synchronous engine: Alembic's command API is
synchronous and project migrations are executed single-threaded at open
time. The application runtime uses async engines; this runner only exists
for schema evolution.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from qualcoder_api.persistence import tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = tables.metadata


def _db_url() -> str:
    url = os.environ.get("QUALCODER_DB_URL") or config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("no sqlalchemy.url configured for alembic")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_db_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
