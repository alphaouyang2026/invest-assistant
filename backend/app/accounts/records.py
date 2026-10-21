"""`Record` — one row of `paper_orders` (spec §3.6): an order, or an
account event (a split adjustment, a delisting settlement) — and the JSON
research runs and model experiments keep it as."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

BUY, SELL, SPLIT_ADJUSTMENT, DELISTING_SETTLEMENT = "buy", "sell", "split_adjustment", "delisting_settlement"
PENDING, FILLED, EXPIRED, SKIPPED = "pending", "filled", "expired", "skipped"
# The one way an order is skipped at the open rather than when planned: a
# split rounded a pending buy down to no whole lot (spec §7.1 step 2).
SPLIT_ROUNDING = "split_rounding"


@dataclass(frozen=True)
class Record:
    """`id` is None until the record is stored; a record with an id that
    comes back from a step replaces the stored one (a pending order that
    filled or expired)."""

    kind: str
    code: str
    signal_date: date
    execution_date: date
    planned_quantity: int = 0
    priority: float | None = None
    reason: Mapping[str, Any] = field(default_factory=dict)
    status: str = PENDING
    outcome_reason: str | None = None
    filled_quantity: int = 0             # a split adjustment: the change in shares, possibly negative
    fill_price: Decimal | None = None    # slippage included
    fees: Decimal = Decimal(0)
    cash_delta: Decimal = Decimal(0)     # buys negative, sells and cashed fractions positive
    id: int | None = None


def record_json(record: Record) -> dict:
    """`record` as research runs and model experiments store and serve it
    (the API's `OrderOut`): dates as ISO text, amounts as numbers, no name."""
    plain = json.loads(json.dumps(asdict(record), default=str, allow_nan=False))
    return {**plain, "name": None, "fees": float(record.fees),
            "fill_price": None if record.fill_price is None else float(record.fill_price),
            "cash_delta": float(record.cash_delta)}
