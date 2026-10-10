"""`plan_orders` (spec §7.2): at a session's close, signals become the
orders for the next open. Pure — no account, no database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.accounts.ledger import Position
from app.accounts.planning import PortfolioRules, plan_orders
from app.strategies import Disposition, Signal

T, NEXT = date(2026, 9, 17), date(2026, 9, 18)
RULES = PortfolioRules(max_positions=3, max_weight=Decimal("0.10"), cash_floor=Decimal("0.05"))
NAV = Decimal("10000000")


def held(code: str, quantity: int) -> Position:
    return Position(code, quantity, date(2026, 9, 1), Decimal(0))


def exit_signal(code: str) -> Signal:
    return Signal(code, Disposition.EXIT, ("trend_broken",), {}, None)


def candidate(code: str, priority: float) -> Signal:
    return Signal(code, Disposition.HOLD, ("strong_buy",), {}, priority)


def summary(records) -> list[tuple]:
    return [(r.kind, r.code, r.planned_quantity, r.status, r.outcome_reason) for r in records]


def test_sells_free_slots_and_the_best_candidates_fill_them_in_whole_lots() -> None:
    """Three slots, two held, one sold: two free. C and D are the best two
    (D before E on a tie, by code). Each aims at 10,000,000 × 10% = 1,000,000:
    C at ¥1,234 → 8 lots; D at ¥50,000 cannot buy one."""
    records = plan_orders(
        day=T, execution_day=NEXT,
        positions={"A": held("A", 300), "B": held("B", 200)},
        exits=[exit_signal("A")],
        candidates=[candidate("F", 0.1), candidate("E", 0.5), candidate("D", 0.5), candidate("C", 0.9)],
        closes={"A": Decimal("900"), "C": Decimal("1234"), "D": Decimal("50000"), "E": Decimal("2000"),
                "F": Decimal("100")},
        cash=Decimal("5000000"), nav=NAV, rules=RULES,
    )

    assert summary(records) == [
        ("sell", "A", 300, "pending", None),
        ("buy", "C", 800, "pending", None),
        ("buy", "D", 0, "skipped", "lot_unaffordable"),
    ]
    assert all((r.signal_date, r.execution_date) == (T, NEXT) for r in records)
    assert records[1].priority == 0.9 and records[0].reason["reason_codes"] == ["trend_broken"]


def test_buys_are_funded_in_turn_from_cash_and_the_sells_less_the_cash_floor() -> None:
    """Each buy aims at 10,000,000 × min(10%, 95% / 10) = 950,000. Budget:
    1,200,000 cash + 100 × 3,000 from selling S − 5% of 10,000,000 =
    1,000,000. X takes 900 × ¥1,000 of it; Y's 200 × ¥3,400 no longer fits.
    A lot too dear is unaffordable before it is over budget."""
    records = plan_orders(
        day=T, execution_day=NEXT,
        positions={"S": held("S", 100)},
        exits=[exit_signal("S")],
        candidates=[candidate("X", 0.9), candidate("Y", 0.5), candidate("Z", 0.3)],
        closes={"S": Decimal("3000"), "X": Decimal("1000"), "Y": Decimal("3400"), "Z": Decimal("2000000")},
        cash=Decimal("1200000"), nav=NAV, rules=PortfolioRules(max_positions=10),
    )

    assert summary(records) == [
        ("sell", "S", 100, "pending", None),
        ("buy", "X", 900, "pending", None),
        ("buy", "Y", 200, "skipped", "insufficient_cash"),
        ("buy", "Z", 0, "skipped", "lot_unaffordable"),
    ]


def test_a_cheaper_candidate_after_one_over_budget_is_still_bought() -> None:
    """Budget 1,200,000 − 500,000 = 700,000: W's 900 × ¥1,000 is over it;
    V's 200 × ¥3,400 = 680,000 fits."""
    records = plan_orders(
        day=T, execution_day=NEXT, positions={}, exits=[],
        candidates=[candidate("W", 0.9), candidate("V", 0.5)],
        closes={"W": Decimal("1000"), "V": Decimal("3400")},
        cash=Decimal("1200000"), nav=NAV, rules=PortfolioRules(max_positions=10),
    )

    assert summary(records) == [
        ("buy", "W", 900, "skipped", "insufficient_cash"),
        ("buy", "V", 200, "pending", None),
    ]


def ranked(code: str, priority: float) -> Signal:
    """A holding's "可持有" with a priority: a strategy that ranks its
    holdings, on a day it ranks."""
    return Signal(code, Disposition.HOLD, ("momentum_rank",), {}, priority)


PRICED = {code: Decimal("1000") for code in "ABCDEFG"}


def test_ranked_holdings_compete_with_the_candidates_and_one_ranked_out_is_sold() -> None:
    """Three places. Held A (0.1) and B (0.9); candidates C (0.5), D (0.3),
    E (0.05). The best three are B, C, D: A is sold as ranked out, its place
    and the free one go to C and D."""
    records = plan_orders(
        day=T, execution_day=NEXT,
        positions={"A": held("A", 300), "B": held("B", 300)},
        exits=[], contenders=[ranked("A", 0.1), ranked("B", 0.9)],
        candidates=[candidate("C", 0.5), candidate("D", 0.3), candidate("E", 0.05)],
        closes=PRICED, cash=Decimal("5000000"), nav=NAV, rules=RULES,
    )

    assert summary(records) == [
        ("sell", "A", 300, "pending", None),
        ("buy", "C", 1000, "pending", None),
        ("buy", "D", 1000, "pending", None),
    ]
    assert records[0].reason == {"disposition": "exit", "reason_codes": ["ranked_out"]}


def test_a_ranked_holding_still_among_the_best_is_kept_as_it_is() -> None:
    """Swaps only: B ranks first and is neither sold nor topped up."""
    records = plan_orders(
        day=T, execution_day=NEXT,
        positions={"B": held("B", 100)},
        exits=[], contenders=[ranked("B", 0.9)],
        candidates=[candidate("C", 0.5)],
        closes=PRICED, cash=Decimal("5000000"), nav=NAV, rules=RULES,
    )

    assert summary(records) == [("buy", "C", 1000, "pending", None)]


def test_a_holding_without_a_rank_that_day_keeps_its_place_and_one_told_to_sell_gives_it_up() -> None:
    """Three places. F has no signal (halted, say): it keeps one. G must be
    sold for its own reason and is not ranked. Two places left for A (0.1),
    B (0.9), C (0.5): A is ranked out; C takes G's place."""
    records = plan_orders(
        day=T, execution_day=NEXT,
        positions={"A": held("A", 100), "B": held("B", 100), "F": held("F", 100), "G": held("G", 100)},
        exits=[exit_signal("G")], contenders=[ranked("A", 0.1), ranked("B", 0.9)],
        candidates=[candidate("C", 0.5)],
        closes=PRICED, cash=Decimal("5000000"), nav=NAV, rules=RULES,
    )

    assert summary(records) == [
        ("sell", "G", 100, "pending", None),
        ("sell", "A", 100, "pending", None),
        ("buy", "C", 1000, "pending", None),
    ]


def test_a_holding_ranked_out_is_sold_even_when_its_replacement_cannot_be_bought() -> None:
    records = plan_orders(
        day=T, execution_day=NEXT,
        positions={"A": held("A", 100)},
        exits=[], contenders=[ranked("A", 0.1)],
        candidates=[candidate("C", 0.5)],
        closes={"A": Decimal("1000"), "C": Decimal("2000000")},
        cash=Decimal("0"), nav=NAV, rules=PortfolioRules(max_positions=1, max_weight=Decimal("0.10")),
    )

    assert summary(records) == [
        ("sell", "A", 100, "pending", None),
        ("buy", "C", 0, "skipped", "lot_unaffordable"),
    ]
