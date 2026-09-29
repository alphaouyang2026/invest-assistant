"""Isolated, immutable research outputs. Source accounts are not foreign keys."""
from sqlalchemy import Column, Integer, MetaData, Table, Text

from app.accounts.tables import JsonText

metadata = MetaData()
runs = Table(
    "manual_research_runs", metadata,
    Column("id", Text, primary_key=True),
    Column("request_key", Text, nullable=False, unique=True),
    Column("request", JsonText, nullable=False),
    Column("config", JsonText, nullable=False),
    Column("retry_of", Text),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("progress", JsonText, nullable=False),
    Column("input_identity", JsonText),
    Column("code_version", Text, nullable=False),
    Column("error", Text),
    Column("result", JsonText),
)
orders = Table(
    "manual_research_orders", metadata,
    Column("run_id", Text, primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("record", JsonText, nullable=False),
)
