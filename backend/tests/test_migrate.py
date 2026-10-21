"""Migrations have to run both ways before any table is worth adding."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.accounts import research_tables
from app.accounts import tables as account_tables
from app.config import Settings
from app.db import create_engine_for
from app.experiments import tables as experiment_tables
from app.market_data import tables as market_tables
from app.migrate import downgrade_to_base, upgrade_to_head


def test_upgrade_stamps_a_revision_and_downgrade_takes_it_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "invest.db"))
    settings = Settings(_env_file=None)
    engine = create_engine_for(settings)

    upgrade_to_head()
    with engine.connect() as connection:
        stamped = connection.execute(text("select count(*) from alembic_version")).scalar_one()

    downgrade_to_base()
    with engine.connect() as connection:
        after = connection.execute(text("select count(*) from alembic_version")).scalar_one()

    assert (stamped, after) == (1, 0)


def test_the_fixture_hands_back_a_migrated_database(migrated_database) -> None:
    """What every later ticket builds its database tests on."""
    with migrated_database.connect() as connection:
        stamped = connection.execute(text("select count(*) from alembic_version")).scalar_one()

    assert stamped == 1


def test_the_migrations_build_every_table_the_code_declares(migrated_database) -> None:
    """Each table the modules read and write, with exactly the columns they
    declare — a column the code expects that no migration adds (or one a
    migration adds that the code has lost) shows up here, not at run time."""
    found = inspect(migrated_database)
    declared = [table for metadata in (market_tables.metadata, account_tables.metadata, research_tables.metadata,
                                       experiment_tables.metadata) for table in metadata.sorted_tables]

    assert {table.name: sorted(c["name"] for c in found.get_columns(table.name)) for table in declared} == {
        table.name: sorted(column.name for column in table.columns) for table in declared}
