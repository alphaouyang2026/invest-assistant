"""`MarketFrame` (spec A.1): `wide` gives any column as a table with a row
per session and a column per code — what the indicator module takes; the
adjustment columns and `listed_through` are what the accounts need."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

from app.market_data import ADJUSTMENT_FACTOR, CLOSE, EX_RIGHTS_TYPE, VOLUME, MarketData
from tests.fakes import FakeJQuants, bar, listed

D1, D2, D3 = date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)


def test_wide_has_a_row_per_session_a_column_per_code_and_nan_where_there_is_no_bar(migrated_database) -> None:
    bars = {
        D1: [bar("13010", D1, "100"), bar("13020", D1, "200")],
        D2: [bar("13010", D2, "101")],
        D3: [bar("13010", D3, "102"), bar("13020", D3, "202")],
    }
    client = FakeJQuants([D1, D2, D3], bars=bars, roster=[listed("13010"), listed("13020")])
    market = MarketData(migrated_database, client, today=lambda: D3)
    market.sync()

    closes = market.read(None, D1, D3).wide(CLOSE)

    assert list(closes.index) == [D1, D2, D3]
    assert list(closes.columns) == ["13010", "13020"]
    assert list(closes["13010"]) == [100.0, 101.0, 102.0]
    assert closes["13020"][D1] == 200.0 and math.isnan(closes["13020"][D2]) and closes["13020"][D3] == 202.0
    assert list(market.read(None, D1, D3).wide(VOLUME)["13010"]) == [1000.0, 1000.0, 1000.0]


def test_each_bar_carries_its_adjustment_factor_and_ex_rights_type(migrated_database) -> None:
    """Exact, as stored: the accounts divide share counts by the factor."""
    bars = {
        D1: [bar("13010", D1, "1000")],
        D2: [bar("13010", D2, "500", adjustment_factor=Decimal("0.5"), ex_rights_type=1)],
        D3: [bar("13010", D3, "510")],
    }
    client = FakeJQuants([D1, D2, D3], bars=bars, roster=[listed("13010")])
    market = MarketData(migrated_database, client, today=lambda: D3)
    market.sync()

    frame = market.read(["13010"], D1, D3).data.xs("13010", level="code")

    assert list(frame[ADJUSTMENT_FACTOR]) == [Decimal("1"), Decimal("0.5"), Decimal("1")]
    assert list(frame[EX_RIGHTS_TYPE]) == [None, 1, None]


def test_listed_through_is_the_last_session_on_the_roster_or_none_while_listed(migrated_database) -> None:
    """How the accounts tell a delisting apart from a halt: by the roster
    on the day, not by what `instruments` says today."""
    bars = {day: [bar("13010", day)] + ([bar("13020", day)] if day != D3 else []) for day in (D1, D2, D3)}
    client = FakeJQuants([D1, D2, D3], bars=bars,
                         roster=lambda day: [listed("13010")] + ([listed("13020")] if day != D3 else []))
    market = MarketData(migrated_database, client, today=lambda: D3)
    market.sync()

    assert market.read(["13010", "13020"], D1, D3).listed_through == {"13010": None, "13020": D2}
