"""`corporate_actions` (spec §7.1 steps 1–2): before the open, splits and
reverse splits change the shares held and the day's orders; a code gone
from the roster is settled at its last close. Pure: made-up bars."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.accounts.ledger import Ledger
from app.accounts.session import Bar, Session, corporate_actions
from tests.records import bought, pending_buy, pending_sell

EARLIER, T, S = date(2026, 9, 1), date(2026, 9, 17), date(2026, 9, 18)
SPLIT, REVERSE_SPLIT, RIGHTS_ISSUE = 1, 2, 3


def ex_rights(factor: str, kind: int) -> Bar:
    price = Decimal("500")
    return Bar(open=price, high=price, low=price, close=price, adjustment_factor=Decimal(factor), ex_rights_type=kind)


def summary(records) -> list[tuple]:
    return [(r.kind, r.code, r.id, r.status, r.outcome_reason, r.planned_quantity, r.filled_quantity, r.cash_delta)
            for r in records]


def test_a_two_for_one_split_doubles_the_shares_and_the_days_orders_follow() -> None:
    ledger = Ledger(Decimal("1000000"), [
        bought(1, "A", EARLIER, 100, "1000"),
        pending_sell(2, "A", signal=T, execution=S, quantity=100),
        pending_buy(3, "B", signal=T, execution=S, quantity=300),
    ])
    session = Session(S, {"A": ex_rights("0.5", SPLIT), "B": ex_rights("0.5", SPLIT)},
                      previous_closes={"A": Decimal("1000"), "B": Decimal("1000")})

    records, warnings = corporate_actions(ledger, session)

    assert summary(records) == [
        ("split_adjustment", "A", None, "filled", None, 0, 100, Decimal(0)),   # 100 → 200 shares
        ("sell", "A", 2, "pending", None, 200, 0, Decimal(0)),                 # sells the whole new holding
        ("buy", "B", 3, "pending", None, 600, 0, Decimal(0)),                  # 300 ÷ 0.5
    ]
    assert warnings == []


def test_a_ten_to_one_reverse_split_pays_out_the_fraction_and_can_drop_a_buy() -> None:
    """105 shares ÷ 10 = 10.5: 10 kept, half a new share paid at ¥50 × 10 = 250.
    A buy of 800 becomes 80 — not a whole lot, so it is dropped."""
    ledger = Ledger(Decimal("1000000"), [
        bought(1, "A", EARLIER, 105, "50"),
        pending_buy(2, "C", signal=T, execution=S, quantity=800),
    ])
    session = Session(S, {"A": ex_rights("10", REVERSE_SPLIT), "C": ex_rights("10", REVERSE_SPLIT)},
                      previous_closes={"A": Decimal("50"), "C": Decimal("50")})

    records, _ = corporate_actions(ledger, session)

    assert summary(records) == [
        ("split_adjustment", "A", None, "filled", None, 0, -95, Decimal("250")),
        ("buy", "C", 2, "skipped", "split_rounding", 0, 0, Decimal(0)),
    ]
    assert Ledger(Decimal("1000000"), [*ledger.records, *records]).positions["A"].quantity == 10


def test_a_rights_issue_changes_nothing_but_is_warned_about() -> None:
    ledger = Ledger(Decimal("1000000"), [bought(1, "A", EARLIER, 100, "1000")])
    session = Session(S, {"A": ex_rights("0.9", RIGHTS_ISSUE)}, previous_closes={"A": Decimal("1000")})

    records, warnings = corporate_actions(ledger, session)

    assert records == [] and len(warnings) == 1 and "A" in warnings[0] and "配股" in warnings[0]


def test_a_code_gone_from_the_roster_is_settled_at_its_last_close_and_its_orders_expire() -> None:
    ledger = Ledger(Decimal("1000000"), [
        bought(1, "A", EARLIER, 200, "500"),
        pending_sell(2, "A", signal=T, execution=S, quantity=200),
    ])
    session = Session(S, {}, previous_closes={"A": Decimal("480")}, delisted=frozenset({"A"}))

    records, _ = corporate_actions(ledger, session)

    assert summary(records) == [
        ("delisting_settlement", "A", None, "filled", None, 0, 200, Decimal("96000")),
        ("sell", "A", 2, "expired", "delisted", 200, 0, Decimal(0)),
    ]
    assert records[0].fill_price == Decimal("480")
