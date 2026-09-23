"""The split check (spec §4.3): after a sync, securities with a new
adjustment factor have their local research closes compared with
J-Quants' own `AdjC` over the 60 sessions before the ex-date.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from app.market_data import MarketData
from tests.fakes import FakeJQuants, bar, listed

SESSIONS = [date(2026, 6, 1) + timedelta(days=n) for n in range(80)]
EX_DATE = SESSIONS[70]
TODAY = SESSIONS[-1]


def split_week(close_before: str = "1000", adjusted_close_before: str = "500") -> FakeJQuants:
    """13010 splits two-for-one on EX_DATE. `history` is J-Quants' view
    today, where every earlier AdjC is already halved."""
    bars = {day: [bar("13010", day, close_before if day < EX_DATE else "500")] for day in SESSIONS}
    bars[EX_DATE] = [bar("13010", EX_DATE, "500", adjustment_factor=Decimal("0.5"), ex_rights_type=1)]
    history = [
        bar("13010", day, close_before if day < EX_DATE else "500",
            adjusted_close=Decimal(adjusted_close_before) if day < EX_DATE else Decimal("500"))
        for day in SESSIONS
    ]
    return FakeJQuants(SESSIONS, bars=bars, roster=[listed("13010")], history={"13010": history})


def synced_daily(migrated_database, client: FakeJQuants):
    """A backfill up to the day before the split, then the daily sync that
    brings the split in — the case the check is for."""
    MarketData(migrated_database, client, today=lambda: SESSIONS[69]).sync()
    client.history_requests.clear()
    return MarketData(migrated_database, client, today=lambda: TODAY).sync()


def test_a_new_split_is_checked_over_the_60_sessions_before_it(migrated_database) -> None:
    client = split_week()

    report = synced_daily(migrated_database, client)

    assert client.history_requests == [("13010", SESSIONS[10], SESSIONS[69])]
    assert not [warning for warning in report.warnings if "拆合股核对" in warning]


def test_research_closes_that_disagree_with_jquants_are_warned_about(migrated_database) -> None:
    client = split_week(adjusted_close_before="400")

    report = synced_daily(migrated_database, client)

    [warning] = [warning for warning in report.warnings if "拆合股核对" in warning]
    assert "13010" in warning and "60" in warning  # all 60 sessions disagree


def test_a_difference_within_jquants_rounding_is_not_a_disagreement(migrated_database) -> None:
    """AdjC keeps one decimal, so up to 0.1 yen apart is rounding however
    cheap the stock. On a ¥21.5 research close that is 0.47 % — far over
    0.1 % — which is why a difference must clear both bounds to count."""
    near = split_week(close_before="43", adjusted_close_before="21.6")
    assert not [w for w in synced_daily(migrated_database, near).warnings if "拆合股核对" in w]


def test_off_by_more_than_rounding_on_a_cheap_stock_is_still_caught(migrated_database) -> None:
    far = split_week(close_before="43", adjusted_close_before="21.8")
    assert [w for w in synced_daily(migrated_database, far).warnings if "拆合股核对" in w]


def test_a_backfill_checks_a_sample_of_twenty_securities_that_had_a_split(migrated_database) -> None:
    codes = [f"{n:04d}0" for n in range(1300, 1330)]
    bars = {day: [bar(code, day) for code in codes] for day in SESSIONS}
    bars[EX_DATE] = [bar(code, EX_DATE, adjustment_factor=Decimal("0.5"), ex_rights_type=1) for code in codes[:25]]
    bars[EX_DATE] += [bar(code, EX_DATE) for code in codes[25:]]
    client = FakeJQuants(SESSIONS, bars=bars, roster=[listed(code) for code in codes])

    MarketData(migrated_database, client, today=lambda: TODAY, rng=random.Random(7)).sync()

    checked = [code for code, _, _ in client.history_requests]
    assert len(checked) == len(set(checked)) == 20
    assert set(checked) <= set(codes[:25])
