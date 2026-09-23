"""The one SQLite engine the process writes through."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from app.config import Settings


def create_engine_for(settings: Settings) -> Engine:
    """An engine for the configured file, creating its directory if needed.

    `var/` is a runtime directory kept out of the repository, so on a fresh
    clone it does not exist yet and SQLite would fail to open the file.
    """
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url)
