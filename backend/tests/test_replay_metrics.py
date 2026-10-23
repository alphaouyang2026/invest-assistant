"""A replay's report figures: what it ended with — a research run's result
and each model experiment replay's alike — and (06a) fill rate, cash share,
returns by year and by range, turnover, order size against ADV20. Every
expected number is worked by hand on five sessions across a new year."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.accounts.ledger import Ledger
from app.accounts.records import Record
from app.accounts.replay import NavPoint, Replay
from app.accounts.replay_metrics import (
    Adv20Usage, PeriodReturn, adv20_usage, annual_turnover, average_cash_share, end_state, fill_rate,
    period_returns, traded, yearly_returns,
)
from tests.records import bought, pending_buy, sold

INITIAL, TOPIX_START = Decimal("1000000"), Decimal("2000")
D = [date(2025, 12, 29), date(2025, 12, 30), date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
NAV = ["1000000", "1100000", "1210000", "990000", "1320000"]
CASH = ["1000000", "550000", "605000", "0", "330000"]   # cash share 1, ½, ½, 0, ¼
TOPIX = ["2000", "2100", "2200", "2000", "2310"]        # curve 1, 1.05, 1.1, 1, 1.155


def point(day: date, nav: str, cash: str, topix: str) -> NavPoint:
    return NavPoint(day, Decimal(nav), Decimal(cash), float(Decimal(nav) / INITIAL),
                    float(Decimal(topix) / TOPIX_START), 0.0)


POINTS = [point(*row) for row in zip(D, NAV, CASH, TOPIX)]


def expired(record: Record, why: str) -> Record:
    return replace(record, status="expired", outcome_reason=why, filled_quantity=0, fill_price=None,
                   cash_delta=Decimal(0))


def skipped(code: str, why: str) -> Record:
    return Record(kind="buy", code=code, signal_date=D[2], execution_date=D[3], status="skipped",
                  outcome_reason=why)


RECORDS = [
    bought(1, "A", D[1], 100, "1000"),
    sold(2, "A", D[2], 100, "1200"),
    bought(3, "B", D[2], 300, "500"),
    expired(bought(4, "C", D[3], 100, "800"), "limit_up_open"),
    expired(sold(5, "B", D[3], 300, "480"), "limit_down_open"),
    expired(sold(6, "B", D[4], 300, "470"), "limit_down_open"),
    expired(bought(7, "D", D[4], 100, "900"), "untradable"),
    skipped("E", "insufficient_cash"),
    skipped("F", "adv20_cap"),
    pending_buy(8, "G", signal=D[4], execution=date(2026, 1, 8), quantity=100),
    Record(kind="split_adjustment", code="B", signal_date=D[3], execution_date=D[3], status="filled",
           filled_quantity=300),
    Record(kind="delisting_settlement", code="H", signal_date=D[4], execution_date=D[4], status="filled",
           filled_quantity=100, fill_price=Decimal("10"), cash_delta=Decimal("1000")),
]


def test_fill_rate_counts_orders_placed_for_an_open_and_why_the_rest_expired() -> None:
    """3 filled, 4 expired; skipped, pending and account events are not orders tried at an open."""
    rate = fill_rate(RECORDS)

    assert (rate.filled, rate.expired, rate.rate) == (3, 4, pytest.approx(3 / 7))
    assert rate.expired_reasons == {"limit_down_open": 2, "limit_up_open": 1, "untradable": 1}
    assert rate.skipped_reasons == {"adv20_cap": 1, "insufficient_cash": 1}
    sells = fill_rate(RECORDS, kind="sell")
    assert (sells.filled, sells.expired, sells.rate, sells.expired_reasons) == (
        1, 2, pytest.approx(1 / 3), {"limit_down_open": 2})
    assert fill_rate([]).rate is None


def test_average_cash_share_is_cash_over_nav_averaged_over_the_closes() -> None:
    assert average_cash_share(POINTS) == pytest.approx((1 + 0.5 + 0.5 + 0 + 0.25) / 5)
    assert average_cash_share([]) is None


def test_each_year_runs_from_the_last_close_of_the_year_before() -> None:
    """2025 from the initial capital: 1 → 1.1; 2026 from 2025's last close:
    1.1 → 1.32 = +20%. TOPIX 1 → 1.05, then 1.05 → 1.155 = +10%."""
    years = yearly_returns(POINTS)

    assert list(years) == [2025, 2026]
    assert years[2025] == PeriodReturn(D[0], D[1], 2, pytest.approx(0.1), pytest.approx(0.05))
    assert years[2026] == PeriodReturn(D[2], D[4], 3, pytest.approx(0.2), pytest.approx(0.1))


def test_a_range_runs_from_the_close_before_it_and_one_with_no_session_has_no_return() -> None:
    """Two folds: D1–D2 from D0's close (1 → 1.21), D3–D4 from D2's (1.21 →
    1.32). A range from before the first session starts at the initial
    capital; a range after the last has nothing in it."""
    found = period_returns(POINTS, [(D[1], D[2]), (D[3], D[4]), (date(2025, 12, 1), D[0]),
                                    (date(2026, 2, 1), date(2026, 2, 28))])

    assert found == [
        PeriodReturn(D[1], D[2], 2, pytest.approx(0.21), pytest.approx(0.1)),
        PeriodReturn(D[3], D[4], 2, pytest.approx(1.32 / 1.21 - 1), pytest.approx(1.155 / 1.1 - 1)),
        PeriodReturn(D[0], D[0], 1, 0.0, 0.0),
        None,
    ]


def test_annual_turnover_is_the_accounts_own() -> None:
    """Bought ¥100,000 + ¥150,000, sold ¥120,000 — expiries and the delisting
    are not trades — over an average NAV of ¥1,124,000 and four periods."""
    assert annual_turnover(POINTS, RECORDS) == pytest.approx((250_000 + 120_000) / 2 / 1_124_000 * 245 / 4)
    assert annual_turnover(POINTS[:1], RECORDS) is None


def test_order_size_over_adv20_takes_the_filled_amount_over_the_signal_days_adv20() -> None:
    """A bought ¥100,000 / ¥2M = 5%, A sold ¥120,000 / ¥1M = 12%, B bought
    ¥150,000 / ¥5M = 3%. The 95th percentile interpolates between 5% and
    12%: 5% + 0.9 × 7%. Only 12% is over a 5% cap; the delisting has no
    ADV20 and is not an order."""
    adv20 = {(D[1], "A"): Decimal("2000000"), (D[2], "A"): Decimal("1000000"), (D[2], "B"): Decimal("5000000")}
    no_b = {key: value for key, value in adv20.items() if key[1] != "B"}

    usage = adv20_usage(RECORDS, adv20, cap=Decimal("0.05"))

    assert usage == Adv20Usage(3, pytest.approx(0.05), pytest.approx(0.113), pytest.approx(0.12), 1, 0)
    assert adv20_usage(RECORDS, no_b).over_cap == 0 and adv20_usage(RECORDS, no_b).without_adv20 == 1
    assert adv20_usage([], adv20) == Adv20Usage(0, None, None, None, 0, 0)


def test_a_replay_ends_with_its_holdings_at_the_last_close_its_pending_orders_and_its_profit() -> None:
    """A bought for ¥100,010 and sold for ¥119,988 (fees ¥10 and ¥12); B
    bought for ¥150,000 and held at ¥520: ¥6,000 not yet realised. The NAV
    went from ¥1,000,000 to ¥1,320,000: the other ¥314,000 is realised."""
    records = [bought(1, "A", D[1], 100, "1000", fees="10"), sold(2, "A", D[2], 100, "1200", fees="12"),
               bought(3, "B", D[2], 300, "500"), pending_buy(4, "G", signal=D[4], execution=date(2026, 1, 8),
                                                            quantity=100)]
    replay = Replay(Ledger(INITIAL, records), POINTS, ["配股", "配股", "退市"])

    ended = end_state(replay, {"B": Decimal("520")})

    assert ended["holdings"] == [{"code": "B", "quantity": 300, "opened_on": D[2].isoformat(), "cost": 150000.0,
                                  "close": 520.0, "value": 156000.0}]
    assert [(o["id"], o["code"], o["status"], o["name"]) for o in ended["pending"]] == [(4, "G", "pending", None)]
    assert ended["warnings"] == ["退市", "配股"]
    assert (ended["total_return"], ended["topix_return"]) == (pytest.approx(0.32), pytest.approx(0.155))
    assert ended["excess_return"] == pytest.approx(0.32 - 0.155)
    assert (ended["trades"], ended["fees"], ended["cash"]) == (3, 22.0, 869978.0)
    assert (ended["unrealised_pnl"], ended["realised_pnl"]) == (6000.0, 314000.0)
    assert traded(records) == {"buy": Decimal("250000"), "sell": Decimal("120000")}
