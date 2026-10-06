"""An account on cross-sectional momentum (ticket 05 C, spec §6.6, §7.2):
the real strategy advanced through the fake J-Quants market, so the
holdings it ranks reach the portfolio rules — a holding ranked out on a
check day is sold and the better stock bought in its place; between check
days nothing changes however the ranks move."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.accounts import Accounts, AccountSpec, PortfolioRules
from tests.account_market import synced

# Weekdays from Monday 24 August to Friday 2 October 2026: check days on
# 1 September and 1 October.
DAYS = [date(2026, 8, 24) + timedelta(days=n) for n in range(40)]
DAYS = [day for day in DAYS if day.weekday() < 5]
SEP_1, SEP_2, OCT_1, OCT_2 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 10, 1), date(2026, 10, 2)


def closes(changes: dict[date, str], first: str = "1000") -> list[str]:
    """A close per session: `first`, then each change from its day on."""
    series, close = [], first
    for day in DAYS:
        close = changes.get(day, close)
        series.append(close)
    return series


def test_a_holding_ranked_out_on_the_check_day_is_swapped_for_the_better_stock(migrated_database) -> None:
    """Two sessions back on 1 September, A is up 10% and B flat: A is bought.
    B overtakes A in mid-September, which changes nothing. On 1 October, A
    is where it was two sessions back and B is up: A is sold as ranked out
    and B bought, both at the next open."""
    prices = {
        "A": closes({date(2026, 8, 31): "1050", SEP_1: "1100", date(2026, 9, 10): "900"}),
        "B": closes({date(2026, 9, 10): "1150", date(2026, 9, 30): "1180", OCT_1: "1250"}),
    }
    accounts = Accounts(migrated_database, synced(migrated_database, prices, sessions=DAYS))
    account = accounts.create(AccountSpec(
        name="横截面动量", strategy="cross_sectional_momentum_v1", start_date=date(2026, 8, 28),
        strategy_params={"momentum_sessions": 2, "skip_sessions": 0, "warmup_sessions": 3},
        rules=PortfolioRules(max_positions=1, max_weight=Decimal("0.5"))))

    accounts.advance(account)

    report = accounts.report(account)
    assert [(o.kind, o.code, o.signal_date, o.execution_date, o.status, o.reason["reason_codes"])
            for o in report.orders if o.kind in ("buy", "sell")] == [
        ("buy", "A", SEP_1, SEP_2, "filled", ["momentum_rank"]),
        ("sell", "A", OCT_1, OCT_2, "filled", ["ranked_out"]),
        ("buy", "B", OCT_1, OCT_2, "filled", ["momentum_rank"]),
    ]
    assert [(h.code, h.opened_on) for h in report.holdings] == [("B", OCT_2)]
