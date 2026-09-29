"""Persist manual-range research independently from paper accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_research_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("request_key", sa.Text, nullable=False, unique=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("config", sa.Text, nullable=False),
        sa.Column("retry_of", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("finished_at", sa.Text),
        sa.Column("progress", sa.Text, nullable=False),
        sa.Column("input_identity", sa.Text),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("result", sa.Text),
    )
    op.create_table(
        "manual_research_orders",
        sa.Column("run_id", sa.Text, sa.ForeignKey("manual_research_runs.id"), primary_key=True),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("record", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("manual_research_orders")
    op.drop_table("manual_research_runs")
