"""Migrations have to run both ways before any table is worth adding."""

from __future__ import annotations

from sqlalchemy import text

from app.config import Settings
from app.db import create_engine_for
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
