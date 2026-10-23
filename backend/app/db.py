"""The one SQLite engine the process writes through, and the JSON column
type the accounts', research and experiment tables all store with."""

from __future__ import annotations

import json

from sqlalchemy import Engine, Text, TypeDecorator, create_engine

from app.config import Settings


def create_engine_for(settings: Settings) -> Engine:
    """An engine for the configured file, creating its directory if needed.

    `var/` is a runtime directory kept out of the repository, so on a fresh
    clone it does not exist yet and SQLite would fail to open the file.
    """
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url)


class JsonText(TypeDecorator):
    """A JSON value stored as its text, keys sorted so the same value is
    always the same text."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)
