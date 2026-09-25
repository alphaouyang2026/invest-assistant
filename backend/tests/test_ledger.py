"""`Ledger` (spec §3.6, A.4): holdings, cash and pending orders are never
stored — they are worked out from the account's records, the same way for
`advance` and for `report`."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.accounts.ledger import Ledger, Position
from app.accounts.records import Record
from tests.records import bought, pending_buy, sold

D1, D2, D3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
CASH = Decimal("1000000")


def test_fills_move_shares_and_cash_and_pending_orders_move_neither() -> None:
    records = [
        bought(1, "72030", D1, 100, "1001", fees="50"),
        pending_buy(2, "67580", signal=D1, execution=D2, quantity=200),
    ]

    ledger = Ledger(CASH, records)

    assert ledger.positions == {"72030": Position("72030", 100, D1, Decimal("100150"))}
    assert ledger.cash == Decimal("899850")  # 1,000,000 − 100 × 1001 − 50
    assert [order.id for order in ledger.pending] == [2]

    ledger = ledger.apply([sold(3, "72030", D3, 100, "1200")])

    assert ledger.positions == {}
    assert ledger.cash == Decimal("1019850")


def test_an_order_filled_replaces_its_pending_self_and_events_move_shares_and_cash() -> None:
    ordered = pending_buy(1, "72030", signal=D1, execution=D2, quantity=100)
    ledger = Ledger(CASH, [ordered])

    ledger = ledger.apply([replace(bought(1, "72030", D2, 100, "1000"), signal_date=D1)])
    assert ledger.pending == [] and ledger.positions["72030"].quantity == 100

    split = Record(id=2, kind="split_adjustment", code="72030", signal_date=D3, execution_date=D3,
                   status="filled", filled_quantity=100)            # two for one: +100 shares
    ledger = ledger.apply([split])
    assert ledger.positions["72030"] == Position("72030", 200, D2, Decimal("100000"))

    settled = Record(id=3, kind="delisting_settlement", code="72030", signal_date=D3, execution_date=D3,
                     status="filled", filled_quantity=200, fill_price=Decimal("480"), cash_delta=Decimal("96000"))
    ledger = ledger.apply([settled])
    assert ledger.positions == {} and ledger.cash == Decimal("996000")
