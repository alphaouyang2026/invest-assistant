"""Empty baseline.

The tables arrive with the module that writes them (ticket 02); this
revision exists so the migration path itself is wired and provable.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
