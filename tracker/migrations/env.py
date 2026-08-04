"""Alembic environment (§6.13).

The only customization over the stock template is URL resolution and two SQLite-specific
settings. URL resolution deserves an explanation: Alembic only needs
``Settings.database_url``, but constructing a full ``Settings`` also requires
``bind_address`` and ``api_token`` (§11.1) — fields that have nothing to do with running a
migration. Requiring those just to run ``alembic upgrade head`` would be exactly the kind
of surprise §11.1 warns against elsewhere: a fresh checkout or a CI job with no
``config.yaml`` and no bearer token configured should still be able to migrate a database.
So this module tries the real settings stack first — a properly configured dev environment
always gets its actual configured database file — and only falls back to
``TRACKER_DATABASE_URL`` (or the documented default) if that fails.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from pydantic import ValidationError
from sqlalchemy import engine_from_config, pool

from tracker.config.settings import load_settings
from tracker.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the migration target URL — see the module docstring for why this isn't
    just ``load_settings().database_url``.
    """
    try:
        return load_settings().database_url
    except ValidationError:
        return os.environ.get("TRACKER_DATABASE_URL", "sqlite:///./tracker.db")


# A caller that already populated ``sqlalchemy.url`` on the ``Config`` object — the test
# suite pointing at an isolated tmp-path database via ``config.set_main_option(...)``
# before calling ``alembic.command.upgrade``, or a future ``-x db_url=...`` — means
# exactly that URL, on purpose. Only fall back to Settings/env resolution when nothing
# more specific was supplied, which is the plain ``alembic upgrade head`` CLI case.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", _database_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite's ALTER TABLE is too limited for most schema changes (no DROP COLUMN
        # before 3.35, no ALTER COLUMN at all); batch mode has Alembic rebuild the table
        # under the hood instead, which is the only way most future migrations here will
        # work at all (§6.13 — this schema is expected to churn for months).
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
