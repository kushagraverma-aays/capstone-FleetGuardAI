"""Alembic environment.

The database URL comes from Pydantic Settings rather than alembic.ini so that
migrations and the application always agree on where the database is, and so
that no credential is committed.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.models import Base

config = context.config

# The URL is deliberately not written back into the Alembic config object.
# alembic.ini is read by configparser, which treats "%" as the start of an
# interpolation token - and a URL-encoded password routinely contains one
# (quote_plus turns "@" into "%40"). Setting it there raises InterpolationError
# before a single migration runs. Passing the URL straight to create_engine in
# run_migrations_online below sidesteps configparser entirely.

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # engine_from_config would read the (intentionally empty) sqlalchemy.url in
    # alembic.ini, so the engine is built from Settings directly. connect_args
    # carries the TLS flag a managed MySQL requires; it is empty when MYSQL_SSL
    # is off, which leaves a local server connecting exactly as before.
    connectable = create_engine(
        settings.sqlalchemy_url,
        poolclass=pool.NullPool,
        connect_args=settings.db_connect_args,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
