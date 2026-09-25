"""The accounts module's two tables (spec §3.5–§3.6).

Holdings, cash and net asset value are not stored: they are worked out
from `paper_orders`. Amounts are TEXT holding a `Decimal`; dates are TEXT
holding `YYYY-MM-DD`; the rules and reasons are JSON text.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("strategy", sa.Text, nullable=False),
        sa.Column("strategy_params", sa.Text, nullable=False),
        sa.Column("portfolio_rules", sa.Text, nullable=False),
        sa.Column("costs", sa.Text, nullable=False),
        sa.Column("start_date", sa.Text, nullable=False),
        sa.Column("advanced_through", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("backtest_data_mark", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("signal_date", sa.Text, nullable=False),
        sa.Column("execution_date", sa.Text, nullable=False),
        sa.Column("planned_quantity", sa.Integer, nullable=False),
        sa.Column("priority", sa.Float),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("outcome_reason", sa.Text),
        sa.Column("filled_quantity", sa.Integer, nullable=False),
        sa.Column("fill_price", sa.Text),
        sa.Column("fees", sa.Text, nullable=False),
        sa.Column("cash_delta", sa.Text, nullable=False),
    )
    op.create_index("paper_orders_by_account", "paper_orders", ["account_id", "id"])


def downgrade() -> None:
    op.drop_index("paper_orders_by_account", "paper_orders")
    op.drop_table("paper_orders")
    op.drop_table("paper_accounts")
