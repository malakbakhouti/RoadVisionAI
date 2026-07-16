"""Alembic async environment — wired to application settings and Base.metadata.

The database schema v4.2 is the source of truth: `autogenerate` is used only
as a CONSISTENCY CHECK (an empty diff proves models == database). Any real
schema change requires an ADR first.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

import app.db.models  # noqa: F401  (register all 24 tables)
from app.core.config import get_settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

EXCLUDE_TABLES = {"spatial_ref_sys"}  # PostGIS internals


def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    # Indexes are owned by the schema v4.2 SQL (source of truth); the ORM
    # reproduction cannot express DESC/partial subtleties, so exclude them
    # from autogenerate comparison to keep the check meaningful.
    if type_ == "index":
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_settings().database_url
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
