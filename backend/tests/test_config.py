"""Settings behaviour the runtime depends on.

The one rule with a branch in it: the service has to start without a
J-Quants key, because the key is only needed once someone asks for data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings


def test_settings_load_when_the_api_key_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.jquants_api_key is None


def test_asking_for_the_api_key_without_one_says_what_to_set(monkeypatch) -> None:
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError) as failure:
        settings.require_jquants_api_key()

    assert "JQUANTS_API_KEY" in str(failure.value)


def test_the_api_key_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("JQUANTS_API_KEY", "key-from-env")
    settings = Settings(_env_file=None)

    assert settings.require_jquants_api_key() == "key-from-env"


def test_the_configured_timezone_is_japan_by_default(monkeypatch) -> None:
    """Everything dated in this system is dated in Tokyo: sessions, the
    18:00 sync, `today`. The setting has to hand back a usable zone, not
    just the string it was given."""
    monkeypatch.delenv("TIMEZONE", raising=False)
    settings = Settings(_env_file=None)

    midnight_utc = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)

    assert midnight_utc.astimezone(settings.tzinfo).hour == 9
