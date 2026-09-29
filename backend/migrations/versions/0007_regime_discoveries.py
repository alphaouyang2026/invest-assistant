"""Interval discoveries: every range a TOPIX regime filter found, kept whole
so a batch can say which of them it ran."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regime_discoveries",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("request_key", sa.Text, nullable=False, unique=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("definition_version", sa.Text, nullable=False),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("parameters", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.Text),
        sa.Column("diagnostics", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("finished_at", sa.Text),
    )
    op.create_table(
        "regime_discovery_intervals",
        sa.Column("discovery_id", sa.Text, sa.ForeignKey("regime_discoveries.id"), primary_key=True),
        sa.Column("interval_id", sa.Integer, primary_key=True),
        sa.Column("start_date", sa.Text, nullable=False),
        sa.Column("end_date", sa.Text, nullable=False),
        sa.Column("sessions", sa.Integer, nullable=False),
        sa.Column("data", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("regime_discovery_intervals")
    op.drop_table("regime_discoveries")
