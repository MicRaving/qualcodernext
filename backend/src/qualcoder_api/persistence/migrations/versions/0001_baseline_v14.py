"""Baseline revision — the complete v14 schema.

Legacy databases are brought to v14 by ``MigrationChain`` (see
``persistence.migration``) and then stamped at this revision. Fresh
databases (``create_new_project_schema``) are also stamped here.

Revision ID: 0001_baseline_v14
Revises:
Create Date: 2026-08-01
"""

from __future__ import annotations

import datetime

import sqlalchemy as sa
from alembic import op

from qualcoder_api.persistence import tables

revision = "0001_baseline_v14"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables.metadata.create_all(bind=op.get_bind())
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS coder_names ("
            "name TEXT UNIQUE NOT NULL, "
            "visibility INTEGER NOT NULL DEFAULT 1 CHECK (visibility IN (0, 1)))"
        )
    )
    for view_name in tables.VISIBILITY_VIEWS:
        tbl = view_name.replace("_visible", "")
        conn.execute(
            sa.text(
                f"CREATE VIEW IF NOT EXISTS {view_name} AS "
                f"SELECT t.* FROM {tbl} t WHERE NOT EXISTS ("
                f"SELECT 1 FROM coder_names c WHERE c.name = t.owner AND c.visibility = 0)"
            )
        )

    now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        sa.text(
            "INSERT INTO project (databaseversion, date, memo, about, bookmarkfile, "
            "bookmarkpos, codername, recently_used_codes) "
            "VALUES ('v18', :date, '', :about, 0, 0, :coder, '')"
        ),
        {"date": now, "about": "QualCoder 4.0", "coder": "default"},
    )


def downgrade() -> None:
    for name in reversed(tables.metadata.tables):
        tables.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
