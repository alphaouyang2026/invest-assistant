"""Research prices (spec §4.3, ADR-0003), read back after a sync.

Every expected number below is worked out by hand from the J-Quants rule
(https://jpx-jquants.com/ja/spec/eq-bars-daily/adj): multiply the
execution price by every later adjustment factor; divide volume by the
later split and reverse-split factors only — a rights issue moves prices,
not volume.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.market_data import CLOSE, EXEC_CLOSE, OPEN, VOLUME, MarketData
from tests.fakes import FakeJQuants, bar, listed

D1, D2, D3 = date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)
SPLIT, REVERSE_SPLIT, RIGHTS_ISSUE = 1, 2, 3


def synced(migrated_database, bars_by_day: dict) -> MarketData:
    client = FakeJQuants(sorted(bars_by_day), bars=bars_by_day, roster=[listed("13010")])
    market = MarketData(migrated_database, client, today=lambda: D3)
    market.sync()
    return market


def column(frame, name: str) -> list:
    return list(frame.data.xs("13010", level="code")[name])


def test_a_two_for_one_split_halves_earlier_prices_and_doubles_earlier_volume(migrated_database) -> None:
    market = synced(migrated_database, {
        D1: [bar("13010", D1, "1000", volume=Decimal("300"))],
        D2: [bar("13010", D2, "510", volume=Decimal("700"),
                 adjustment_factor=Decimal("0.5"), ex_rights_type=SPLIT)],
        D3: [bar("13010", D3, "520", volume=Decimal("800"))],
    })

    frame = market.read(["13010"], D1, D3)

    assert column(frame, CLOSE) == [500.0, 510.0, 520.0]
    assert column(frame, OPEN) == [500.0, 510.0, 520.0]
    assert column(frame, VOLUME) == [600.0, 700.0, 800.0]
    assert column(frame, EXEC_CLOSE) == [Decimal("1000"), Decimal("510"), Decimal("520")]


def test_a_ten_to_one_reverse_split_multiplies_earlier_prices_by_ten(migrated_database) -> None:
    market = synced(migrated_database, {
        D1: [bar("13010", D1, "48", volume=Decimal("5000"))],
        D2: [bar("13010", D2, "490", volume=Decimal("450"),
                 adjustment_factor=Decimal("10"), ex_rights_type=REVERSE_SPLIT)],
        D3: [bar("13010", D3, "500")],
    })

    frame = market.read(["13010"], D1, D2)

    assert column(frame, CLOSE) == [480.0, 490.0]
    assert column(frame, VOLUME) == [500.0, 450.0]


def test_a_rights_issue_adjusts_earlier_prices_but_not_volume(migrated_database) -> None:
    market = synced(migrated_database, {
        D1: [bar("13010", D1, "1000", volume=Decimal("300"))],
        D2: [bar("13010", D2, "950", volume=Decimal("400"),
                 adjustment_factor=Decimal("0.95"), ex_rights_type=RIGHTS_ISSUE)],
        D3: [bar("13010", D3, "960")],
    })

    frame = market.read(["13010"], D1, D2)

    assert column(frame, CLOSE) == [950.0, 950.0]
    assert column(frame, VOLUME) == [300.0, 400.0]


def test_factors_after_the_requested_range_still_apply_and_compound(migrated_database) -> None:
    """Reading only D1 must give the same D1 as reading the whole history:
    the split on D2 and the rights issue on D3 are both after it."""
    market = synced(migrated_database, {
        D1: [bar("13010", D1, "1000")],
        D2: [bar("13010", D2, "500", adjustment_factor=Decimal("0.5"), ex_rights_type=SPLIT)],
        D3: [bar("13010", D3, "450", adjustment_factor=Decimal("0.9"), ex_rights_type=RIGHTS_ISSUE)],
    })

    assert column(market.read(["13010"], D1, D1), CLOSE) == [450.0]
    assert column(market.read(["13010"], D1, D3), CLOSE) == [450.0, 450.0, 450.0]


def test_research_closes_are_continuous_across_a_split_with_no_false_crash(migrated_database) -> None:
    """The reason ADR-0003 exists: the execution close halves on the
    ex-date; the research close must not."""
    market = synced(migrated_database, {
        D1: [bar("13010", D1, "2000")],
        D2: [bar("13010", D2, "1004", adjustment_factor=Decimal("0.5"), ex_rights_type=SPLIT)],
        D3: [bar("13010", D3, "1010")],
    })

    closes = market.read(["13010"], D1, D3).wide(CLOSE)["13010"]

    assert closes.pct_change().dropna().tolist() == pytest.approx([0.004, 1010 / 1004 - 1])
