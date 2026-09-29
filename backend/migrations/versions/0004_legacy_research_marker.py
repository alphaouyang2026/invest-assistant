"""Compatibility marker for the rolled-back 0004 research implementation.

Some existing databases are already stamped 0004 and retain its research
tables. Do not repurpose or drop those tables. New manual research is 0005.
"""
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
