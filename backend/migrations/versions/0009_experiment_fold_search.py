"""Model experiments (06b): each fold keeps the parameter sets its model
tried on the validation stretch, how each did, and which it kept — null
for a model that tried only one."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_experiment_folds") as table:
        table.add_column(sa.Column("search", sa.Text))


def downgrade() -> None:
    with op.batch_alter_table("model_experiment_folds") as table:
        table.drop_column("search")
