"""Running Alembic from Python, so the container, the tests and the CLI
all take the same path to the same `alembic.ini`.

No database argument: `migrations/env.py` builds `Settings` from the
environment, exactly as the `alembic` command does. Pointing these at
another database means setting `DATABASE_PATH`, and there is only one
way to do it.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _config() -> Config:
    config = Config(_ALEMBIC_INI)
    config.set_main_option("script_location", str(_ALEMBIC_INI.parent / "migrations"))
    return config


def upgrade_to_head() -> None:
    command.upgrade(_config(), "head")


def downgrade_to_base() -> None:
    command.downgrade(_config(), "base")


if __name__ == "__main__":  # `python -m app.migrate` — how the container migrates
    upgrade_to_head()
