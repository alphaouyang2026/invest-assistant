"""`open_session` (spec §7.3): one open's orders, all at once — sells
before buys, buys by priority, what a sell brings in spendable at once,
each order filled or expired by the rules. Pure: made-up bars, no account."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.accounts.session import Bar, Costs, Session, open_session, replace_sells
from tests.records import pending_buy, pending_sell

T, S = date(2026, 9, 17), date(2026, 9, 18)
SLIPPAGE = Costs(slippage=Decimal("0.001"))


def bar(open_: str, *, high: str | None = None, low: str | None = None, up: bool = False, down: bool = False,
        untradable: bool = False) -> Bar:
    price = Decimal(open_)
    return Bar(open=price, high=Decimal(high) if high else price, low=Decimal(low) if low else price, close=price,
               upper_limit_hit=up, lower_limit_hit=down, untradable=untradable)


def outcome(records) -> dict:
    return {r.code: (r.status, r.outcome_reason, r.filled_quantity, r.fill_price, r.cash_delta) for r in records}


def test_sells_go_first_and_what_they_bring_in_pays_for_the_buys() -> None:
    """No cash to start with. Selling A: 100 × 1,000 × 0.999 = 99,900 in;
    then buying B: 100 × 900 × 1.001 = 90,090 out."""
    orders = [pending_buy(1, "B", signal=T, execution=S, quantity=100, priority=0.5),
              pending_sell(2, "A", signal=T, execution=S, quantity=100)]

    filled = open_session(orders, Session(S, {"A": bar("1000"), "B": bar("900")}), cash=Decimal(0), costs=SLIPPAGE)

    assert outcome(filled) == {
        "A": ("filled", None, 100, Decimal("999.000"), Decimal("99900.000")),
        "B": ("filled", None, 100, Decimal("900.900"), Decimal("-90090.000")),
    }
    assert [r.id for r in filled] == [2, 1]  # in the order they were carried out


@pytest.mark.parametrize(("kind", "day_bar", "expected"), [
    ("sell", bar("1000", untradable=True), ("expired", "untradable")),
    ("buy", Bar(open=None, high=None, low=None, close=None), ("expired", "untradable")),
    ("buy", None, ("expired", "untradable")),                                    # no bar at all that day
    ("sell", bar("900", high="950", down=True), ("expired", "limit_down_open")),  # opened at the day's low, on the limit
    ("buy", bar("1100", low="1050", up=True), ("expired", "limit_up_open")),      # opened at the day's high, on the limit
    ("buy", bar("1000", high="1100", up=True), ("filled", None)),                # the limit was only touched later
], ids=["halted", "no_open", "no_bar", "limit_down", "limit_up", "limit_later"])
def test_an_order_that_cannot_be_carried_out_at_the_open_expires(kind, day_bar, expected) -> None:
    make = pending_sell if kind == "sell" else pending_buy
    order = make(1, "A", signal=T, execution=S, quantity=100)
    bars = {} if day_bar is None else {"A": day_bar}

    [result] = open_session([order], Session(S, bars), cash=Decimal("1000000"), costs=SLIPPAGE)

    assert (result.status, result.outcome_reason) == expected
    if expected[0] == "expired":
        assert (result.filled_quantity, result.cash_delta) == (0, 0)


def test_short_of_cash_a_buy_takes_fewer_lots_and_with_none_left_it_expires() -> None:
    """150,000 to spend; commission 0.05% with a ¥100 minimum, no slippage.
    C (first by priority) wants 200 × ¥1,000 = 200,000 + 100 fee: too much,
    so 100 shares, 100,000 + 100. D wants 100 × ¥600 = 60,100 of the 49,900 left."""
    costs = Costs(commission_rate=Decimal("0.0005"), commission_min=Decimal("100"), slippage=Decimal(0))
    orders = [pending_buy(1, "D", signal=T, execution=S, quantity=100, priority=0.5),
              pending_buy(2, "C", signal=T, execution=S, quantity=200, priority=0.9)]

    results = open_session(orders, Session(S, {"C": bar("1000"), "D": bar("600")}), cash=Decimal("150000"), costs=costs)

    assert outcome(results) == {
        "C": ("filled", None, 100, Decimal("1000"), Decimal("-100100")),
        "D": ("expired", "insufficient_cash", 0, None, Decimal(0)),
    }
    assert results[0].fees == Decimal("100")  # 100,000 × 0.05% = 50, below the minimum


def test_a_sell_that_expired_at_the_open_is_placed_again_for_the_next_one() -> None:
    """Spec §7.1 step 4: no new signal needed. A buy that expired is not; a
    sell that expired because the code was delisted is not either."""
    results = [
        replace(pending_sell(1, "A", signal=date(2026, 9, 16), execution=T, quantity=300), status="expired",
                outcome_reason="untradable"),
        replace(pending_buy(2, "B", signal=date(2026, 9, 16), execution=T, quantity=100), status="expired",
                outcome_reason="limit_up_open"),
        replace(pending_sell(3, "C", signal=date(2026, 9, 16), execution=T, quantity=100), status="expired",
                outcome_reason="delisted"),
    ]

    [again] = replace_sells(results, day=T, execution_day=S)

    assert (again.id, again.kind, again.code, again.planned_quantity, again.status) == (None, "sell", "A", 300, "pending")
    assert (again.signal_date, again.execution_date) == (T, S)
    assert again.reason["replaces"] == 1
