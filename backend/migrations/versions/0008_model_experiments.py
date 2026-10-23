"""Model experiments (06a): the frozen contract, each fold's model artifact,
the out-of-fold scores kept on the decision days, and every replay's
results, ledger and day-by-day decisions — isolated from paper accounts and
manual research. Each attempt also keeps what it read and when, and what
kind of failure stopped it: facts of the attempt, beside its contract."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_experiments",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("request_key", sa.Text, nullable=False, unique=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("contract", sa.Text, nullable=False),
        sa.Column("contract_hash", sa.Text, nullable=False),
        sa.Column("retry_of", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("finished_at", sa.Text),
        sa.Column("progress", sa.Text, nullable=False),
        sa.Column("input_fingerprint", sa.Text),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("evidence_status", sa.Text),
        sa.Column("report", sa.Text),
        sa.Column("data_read", sa.Text),
        sa.Column("error_code", sa.Text),
    )
    op.create_table(
        "model_experiment_folds",
        sa.Column("experiment_id", sa.Text, sa.ForeignKey("model_experiments.id"), primary_key=True),
        sa.Column("model", sa.Text, primary_key=True),
        sa.Column("fold", sa.Integer, primary_key=True),
        sa.Column("train_from", sa.Text, nullable=False),
        sa.Column("train_to", sa.Text, nullable=False),
        sa.Column("test_from", sa.Text, nullable=False),
        sa.Column("test_to", sa.Text, nullable=False),
        sa.Column("samples", sa.Integer, nullable=False),
        sa.Column("seconds", sa.Float, nullable=False),
        sa.Column("artifact", sa.Text),
        sa.Column("artifact_hash", sa.Text),
        sa.Column("error", sa.Text),
    )
    op.create_table(
        "model_experiment_scores",
        sa.Column("experiment_id", sa.Text, sa.ForeignKey("model_experiments.id"), primary_key=True),
        sa.Column("model", sa.Text, primary_key=True),
        sa.Column("as_of", sa.Text, primary_key=True),
        sa.Column("fold", sa.Integer, nullable=False),
        sa.Column("artifact_hash", sa.Text, nullable=False),
        sa.Column("scores", sa.Text, nullable=False),
    )
    op.create_table(
        "model_experiment_replays",
        sa.Column("experiment_id", sa.Text, sa.ForeignKey("model_experiments.id"), primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("scenario", sa.Text, nullable=False),
        sa.Column("costs", sa.Text, nullable=False),
        sa.Column("result", sa.Text, nullable=False),
    )
    op.create_table(
        "model_experiment_orders",
        sa.Column("experiment_id", sa.Text, primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("record", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["experiment_id", "position"],
                                ["model_experiment_replays.experiment_id", "model_experiment_replays.position"]),
    )
    op.create_table(
        "model_experiment_days",
        sa.Column("experiment_id", sa.Text, primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("day", sa.Text, primary_key=True),
        sa.Column("decision_day", sa.Boolean, nullable=False),
        sa.Column("record", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["experiment_id", "position"],
                                ["model_experiment_replays.experiment_id", "model_experiment_replays.position"]),
    )


def downgrade() -> None:
    op.drop_table("model_experiment_days")
    op.drop_table("model_experiment_orders")
    op.drop_table("model_experiment_replays")
    op.drop_table("model_experiment_scores")
    op.drop_table("model_experiment_folds")
    op.drop_table("model_experiments")
