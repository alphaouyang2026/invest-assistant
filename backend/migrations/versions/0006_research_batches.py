"""Research batches: one configuration over several ranges, each attempt an
ordinary manual research run."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_batches",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("request_key", sa.Text, nullable=False, unique=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("config", sa.Text, nullable=False),
        sa.Column("discovery_id", sa.Text),
        sa.Column("selection", sa.Text, nullable=False),
        sa.Column("input_check", sa.Text),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_table(
        "research_batch_segments",
        sa.Column("batch_id", sa.Text, sa.ForeignKey("research_batches.id"), primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("interval_id", sa.Integer),
        sa.Column("start_date", sa.Text, nullable=False),
        sa.Column("end_date", sa.Text, nullable=False),
    )
    op.create_table(
        "research_batch_attempts",
        sa.Column("batch_id", sa.Text, primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Text, sa.ForeignKey("manual_research_runs.id"), nullable=False, unique=True),
        sa.Column("request_key", sa.Text, unique=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["batch_id", "position"],
                                ["research_batch_segments.batch_id", "research_batch_segments.position"]),
    )


def downgrade() -> None:
    op.drop_table("research_batch_attempts")
    op.drop_table("research_batch_segments")
    op.drop_table("research_batches")
