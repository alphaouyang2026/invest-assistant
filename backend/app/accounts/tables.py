"""The two account tables, as SQLAlchemy Core sees them (spec §3.5–§3.6).

Private to the accounts module (spec §2): nothing outside `app.accounts`
imports this.
"""

from __future__ import annotations

from sqlalchemy import Column, Float, Integer, MetaData, Table, Text

from app.db import JsonText
from app.market_data.tables import DecimalText, IsoDate

metadata = MetaData()

paper_accounts = Table(
    "paper_accounts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("strategy", Text, nullable=False),
    Column("strategy_params", JsonText, nullable=False),
    Column("portfolio_rules", JsonText, nullable=False),
    Column("costs", JsonText, nullable=False),
    Column("start_date", IsoDate, nullable=False),
    Column("advanced_through", IsoDate),
    Column("status", Text, nullable=False),
    Column("backtest_data_mark", JsonText),
    Column("created_at", Text, nullable=False),
)

paper_orders = Table(
    "paper_orders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("account_id", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("signal_date", IsoDate, nullable=False),
    Column("execution_date", IsoDate, nullable=False),
    Column("planned_quantity", Integer, nullable=False),
    Column("priority", Float),
    Column("reason", JsonText, nullable=False),
    Column("status", Text, nullable=False),
    Column("outcome_reason", Text),
    Column("filled_quantity", Integer, nullable=False),
    Column("fill_price", DecimalText),
    Column("fees", DecimalText, nullable=False),
    Column("cash_delta", DecimalText, nullable=False),
)
