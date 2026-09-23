"""Quality status (spec §4.4): judged per row as it is written, worst wins."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.market_data import QUALITY, MarketData
from tests.fakes import FakeJQuants, bar, listed

DAY = date(2026, 9, 24)
D = Decimal

CASES = {
    "halted: no prices at all": (dict(close=None), "untradable"),
    # §4.4 names a missing close; "prices complete" in the `excluded` row
    # implies any missing price is worse than that, so it is untradable too.
    "a close but no open": (dict(open=None), "untradable"),
    "a zero price": (dict(low=D("0")), "untradable"),
    "a negative price": (dict(open=D("-1"), high=D("-1"), low=D("-1"), close=D("-1")), "untradable"),
    "high below the close": (dict(high=D("99")), "untradable"),
    "low above the open": (dict(low=D("101")), "untradable"),
    "no volume": (dict(volume=None), "excluded"),
    "no turnover": (dict(turnover=None), "excluded"),
    "no volume and no prices: the worse wins": (dict(close=None, volume=None), "untradable"),
    "ordinary": (dict(), "ok"),
}


@pytest.mark.parametrize("fields, expected", CASES.values(), ids=CASES.keys())
def test_each_bar_is_marked_as_it_is_written(migrated_database, fields, expected) -> None:
    client = FakeJQuants([DAY], bars={DAY: [bar("13010", DAY, **fields)]}, roster=[listed("13010")])
    market = MarketData(migrated_database, client, today=lambda: DAY)

    market.sync()

    assert market.read(["13010"], DAY, DAY).data.loc[("13010", DAY), QUALITY] == expected
