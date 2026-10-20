"""A model experiment's records (migration 0008), isolated from paper
accounts and manual research: nothing here is a foreign key to either.

- experiments: the frozen contract and its hash, the job's status, the
  research input fingerprint, the code version and the report;
- folds: each model's fold — its dates, how many samples it was fitted on,
  its JSON artifact and hash, or why it failed;
- scores: the out-of-fold scores kept, one row per model and decision day;
- replays: each replay's costs and result (NAV with cash, figures, holdings);
- orders and days: each replay's ledger, and what it decided day by day.
"""
from sqlalchemy import Boolean, Column, Float, Integer, MetaData, Table, Text

from app.accounts.tables import JsonText

metadata = MetaData()
experiments = Table(
    "model_experiments", metadata,
    Column("id", Text, primary_key=True),
    Column("request_key", Text, nullable=False, unique=True),
    Column("request", JsonText, nullable=False),
    Column("contract", JsonText, nullable=False),
    Column("contract_hash", Text, nullable=False),
    Column("retry_of", Text),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("progress", JsonText, nullable=False),
    Column("input_fingerprint", JsonText),
    Column("code_version", Text, nullable=False),
    Column("error", Text),
    Column("evidence_status", Text),  # the report's, for the history
    Column("report", JsonText),
)
folds = Table(
    "model_experiment_folds", metadata,
    Column("experiment_id", Text, primary_key=True),
    Column("model", Text, primary_key=True),  # "model", "baseline_1", …
    Column("fold", Integer, primary_key=True),
    Column("train_from", Text, nullable=False),
    Column("train_to", Text, nullable=False),
    Column("test_from", Text, nullable=False),
    Column("test_to", Text, nullable=False),
    Column("samples", Integer, nullable=False),
    Column("seconds", Float, nullable=False),
    Column("artifact", JsonText),
    Column("artifact_hash", Text),
    Column("error", Text),
)
scores = Table(
    "model_experiment_scores", metadata,
    Column("experiment_id", Text, primary_key=True),
    Column("model", Text, primary_key=True),
    Column("as_of", Text, primary_key=True),  # a decision day
    Column("fold", Integer, nullable=False),
    Column("artifact_hash", Text, nullable=False),
    Column("scores", JsonText, nullable=False),  # code → score
)
replays = Table(
    "model_experiment_replays", metadata,
    Column("experiment_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),  # 1..N, the model's first
    Column("model", Text, nullable=False),
    Column("scenario", Text, nullable=False),  # "base" / "stress"
    Column("costs", JsonText, nullable=False),
    Column("result", JsonText, nullable=False),
)
orders = Table(
    "model_experiment_orders", metadata,
    Column("experiment_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("record", JsonText, nullable=False),
)
days = Table(
    "model_experiment_days", metadata,
    Column("experiment_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("day", Text, primary_key=True),
    Column("decision_day", Boolean, nullable=False),
    Column("record", JsonText, nullable=False),
)
