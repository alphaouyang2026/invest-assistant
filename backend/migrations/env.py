"""Alembic environment: the URL always comes from app.config."""

from __future__ import annotations

from alembic import context

from app.config import Settings
from app.db import create_engine_for


def run_migrations_offline() -> None:
    context.configure(url=Settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine_for(Settings())
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
