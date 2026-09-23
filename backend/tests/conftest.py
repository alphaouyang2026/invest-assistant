"""Fixtures shared by every ticket's database tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from app.config import Settings
from app.db import create_engine_for
from app.migrate import upgrade_to_head


@pytest.fixture
def migrated_database(tmp_path, monkeypatch) -> Iterator[Engine]:
    """A throwaway SQLite file with every migration applied.

    `DATABASE_PATH` is set rather than passed, because that is the only
    way the migrations are ever pointed at a database — the container and
    the command line do the same thing.
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "invest.db"))
    upgrade_to_head()

    engine = create_engine_for(Settings(_env_file=None))
    try:
        yield engine
    finally:
        engine.dispose()
