"""Account records for tests that need no database: what `paper_orders`
rows hold (spec §3.6), built in a line each."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.accounts.records import Record


def bought(id: int, code: str, day: date, quantity: int, price: str, *, fees: str = "0") -> Record:
    """A buy filled at the open of `day` (ordered the session before)."""
    paid = Decimal(price) * quantity + Decimal(fees)
    return Record(id=id, kind="buy", code=code, signal_date=day, execution_date=day, planned_quantity=quantity,
                  status="filled", filled_quantity=quantity, fill_price=Decimal(price), fees=Decimal(fees),
                  cash_delta=-paid)


def sold(id: int, code: str, day: date, quantity: int, price: str, *, fees: str = "0") -> Record:
    received = Decimal(price) * quantity - Decimal(fees)
    return Record(id=id, kind="sell", code=code, signal_date=day, execution_date=day, planned_quantity=quantity,
                  status="filled", filled_quantity=quantity, fill_price=Decimal(price), fees=Decimal(fees),
                  cash_delta=received)


def pending_buy(id: int | None, code: str, *, signal: date, execution: date, quantity: int,
                priority: float | None = None) -> Record:
    return Record(id=id, kind="buy", code=code, signal_date=signal, execution_date=execution,
                  planned_quantity=quantity, priority=priority)


def pending_sell(id: int | None, code: str, *, signal: date, execution: date, quantity: int) -> Record:
    return Record(id=id, kind="sell", code=code, signal_date=signal, execution_date=execution,
                  planned_quantity=quantity)
