"""Declarative base for all ORM models (Step 3 will populate app/db/models/).

The naming convention mirrors the constraint-naming style of schema v4.2
so that Alembic autogenerate diffs stay clean against the deployed database.
The database schema is the single source of truth — models are written to
match it, never the reverse.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "idx_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "chk_%(table_name)s_%(constraint_name)s",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
