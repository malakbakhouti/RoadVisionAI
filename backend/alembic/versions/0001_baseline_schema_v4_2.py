"""Baseline — deploy the verified production schema v4.2 (single source of truth).

Fresh environments:   `alembic upgrade head` executes the full v4.2 SQL
                      (24 tables, 14 ENUMs, 63+ indexes, 16 triggers, 4 functions).
Docker environments:  the schema is already created by
                      /docker-entrypoint-initdb.d — run `alembic stamp head`
                      once to mark the baseline as applied.

Revision ID: 0001_baseline
Revises:
"""
from pathlib import Path

import sqlparse
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "schema_v4.2.sql"


def upgrade() -> None:
    # asyncpg cannot run multi-command scripts in one prepared statement,
    # so split into individual statements (sqlparse is dollar-quote aware,
    # which keeps trigger-function bodies $$ ... $$ intact).
    sql = _SQL_FILE.read_text(encoding="utf-8")
    for statement in sqlparse.split(sql):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    raise RuntimeError(
        "Baseline is irreversible by design — restoring pre-v4.2 state "
        "means dropping the entire database."
    )
