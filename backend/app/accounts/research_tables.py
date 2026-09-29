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
# 04b-B: one configuration over several ranges. Every attempt at a segment is
# an ordinary manual_research_runs row; statuses are derived from those runs.
batches = Table(
    "research_batches", metadata,
    Column("id", Text, primary_key=True),
    Column("request_key", Text, nullable=False, unique=True),
    Column("request", JsonText, nullable=False),
    Column("config", JsonText, nullable=False),  # frozen base configuration, without the range
    Column("discovery_id", Text),
    Column("selection", JsonText, nullable=False),
    Column("input_check", JsonText),
    Column("code_version", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
batch_segments = Table(
    "research_batch_segments", metadata,
    Column("batch_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("interval_id", Integer),
    Column("start_date", Text, nullable=False),
    Column("end_date", Text, nullable=False),
)
batch_attempts = Table(
    "research_batch_attempts", metadata,
    Column("batch_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("attempt", Integer, primary_key=True),
    Column("run_id", Text, nullable=False, unique=True),
    Column("request_key", Text, unique=True),  # only retries carry a client key
    Column("created_at", Text, nullable=False),
)
# 04b-B: which ranges a TOPIX regime filter found. Every candidate is kept,
# numbered 1..N oldest first, whether or not a batch selects it.
discoveries = Table(
    "regime_discoveries", metadata,
    Column("id", Text, primary_key=True),
    Column("request_key", Text, nullable=False, unique=True),
    Column("request", JsonText, nullable=False),
    Column("definition_version", Text, nullable=False),
    Column("definition", JsonText, nullable=False),
    Column("parameters", JsonText, nullable=False),  # search_from, search_to, trend, volatility
    Column("status", Text, nullable=False),
    Column("fingerprint", JsonText),
    Column("diagnostics", JsonText),
    Column("error", Text),
    Column("code_version", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("finished_at", Text),
)
discovery_intervals = Table(
    "regime_discovery_intervals", metadata,
    Column("discovery_id", Text, primary_key=True),
    Column("interval_id", Integer, primary_key=True),
    Column("start_date", Text, nullable=False),
    Column("end_date", Text, nullable=False),
    Column("sessions", Integer, nullable=False),
    Column("data", JsonText, nullable=False),
)
