"""Where the SQLite file ends up, and that it is reachable."""

from __future__ import annotations

from sqlalchemy import text

from app.config import Settings
from app.db import create_engine_for


def test_the_engine_writes_to_the_configured_file(tmp_path, monkeypatch) -> None:
    database = tmp_path / "invest.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))

    engine = create_engine_for(Settings(_env_file=None))
    with engine.begin() as connection:
        connection.execute(text("create table probe (x integer)"))

    assert database.exists()


def test_a_missing_directory_is_created_rather_than_failing(tmp_path, monkeypatch) -> None:
    """`var/` is not in the repository, so a fresh clone has no directory yet."""
    database = tmp_path / "var" / "invest.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))

    engine = create_engine_for(Settings(_env_file=None))
    with engine.begin() as connection:
        connection.execute(text("create table probe (x integer)"))

    assert database.exists()
