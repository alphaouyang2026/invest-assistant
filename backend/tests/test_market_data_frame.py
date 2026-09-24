"""`MarketFrame.wide` (spec A.1): any column as a table with a row per
session and a column per code — what the indicator module takes."""

from __future__ import annotations

import math
from datetime import date

from app.market_data import CLOSE, VOLUME, MarketData
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
