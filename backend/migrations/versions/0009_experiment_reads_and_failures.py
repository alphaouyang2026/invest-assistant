"""Model experiments (06a): what each attempt read and when, and what kind
of failure stopped one — missing data told apart from the rest. Both are
facts of the attempt, kept beside its frozen contract, never in it."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_experiments", sa.Column("data_read", sa.Text))
    op.add_column("model_experiments", sa.Column("error_code", sa.Text))


def downgrade() -> None:
    with op.batch_alter_table("model_experiments") as table:
        table.drop_column("error_code")
        table.drop_column("data_read")
