"""The market data module's four tables (spec §3.1–§3.4).

Prices, amounts and factors are TEXT holding a `Decimal`; dates are TEXT
holding `YYYY-MM-DD`, so they sort and compare as dates.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_en", sa.Text, nullable=False),
        sa.Column("scale_category", sa.Text, nullable=False),
        sa.Column("first_listed_seen", sa.Text),
        sa.Column("last_listed_seen", sa.Text),
    )
    op.create_table(
        "segment_periods",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("valid_from", sa.Text, primary_key=True),
        sa.Column("valid_to", sa.Text),
        sa.Column("market_code", sa.Text, nullable=False),
        sa.Column("product_category", sa.Text, nullable=False),
        sa.Column("sector33", sa.Text, nullable=False),
    )
    op.create_table(
        "daily_bars",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("date", sa.Text, primary_key=True),
        sa.Column("open", sa.Text),
        sa.Column("high", sa.Text),
        sa.Column("low", sa.Text),
        sa.Column("close", sa.Text),
        sa.Column("volume", sa.Text),
        sa.Column("turnover", sa.Text),
        sa.Column("adjustment_factor", sa.Text, nullable=False),
        sa.Column("ex_rights_type", sa.Integer),
        sa.Column("upper_limit_hit", sa.Boolean, nullable=False),
        sa.Column("lower_limit_hit", sa.Boolean, nullable=False),
        sa.Column("quality_status", sa.Text, nullable=False),
    )
    # Whole-market reads and "what is the latest date" go by date, not code.
    op.create_index("ix_daily_bars_date", "daily_bars", ["date"])
    op.create_table(
        "trading_calendar",
        sa.Column("date", sa.Text, primary_key=True),
        sa.Column("holiday_division", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("trading_calendar")
    op.drop_index("ix_daily_bars_date", table_name="daily_bars")
    op.drop_table("daily_bars")
    op.drop_table("segment_periods")
    op.drop_table("instruments")
