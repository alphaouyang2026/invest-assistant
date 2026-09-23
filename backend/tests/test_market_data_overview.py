"""`MarketData.overview()`: what the data page shows about the data itself.

Cross-row quality problems are worked out here, when asked, never stored
(spec §4.4): whole sessions without bars, securities with holes in their
history, and how much is untradable.
"""

from __future__ import annotations

from datetime import date

from app.market_data import MarketData
from tests.fakes import FakeJQuants, bar, listed

D1, D2, D3, D4 = date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)


def test_an_empty_database_has_nothing_to_report(migrated_database) -> None:
    overview = MarketData(migrated_database, FakeJQuants([]), today=lambda: D4).overview()

    assert (overview.latest_date, overview.securities, overview.bar_rows) == (None, 0, 0)
    assert overview.quality.missing_sessions == []
    assert overview.quality.gaps == {}
    assert overview.quality.untradable_rows == 0


def test_the_overview_counts_what_the_sync_stored_and_finds_what_is_missing(migrated_database) -> None:
    bars = {
        D1: [bar("13010", D1), bar("13020", D1)],
        # D2: J-Quants returned nothing at all
        D3: [bar("13010", D3)],  # 13020 has a hole here
        D4: [bar("13010", D4, close=None), bar("13020", D4)],  # 13010 halted
    }
    client = FakeJQuants([D1, D2, D3, D4], bars=bars, roster=[listed("13010"), listed("13020")])
    market = MarketData(migrated_database, client, today=lambda: D4)
    market.sync()

    overview = market.overview()

    assert overview.latest_date == D4
    assert overview.securities == 2
    assert overview.bar_rows == 5
    assert overview.quality.missing_sessions == [D2]
    assert overview.quality.gaps == {"13020": 1}
    assert (overview.quality.untradable_rows, overview.quality.untradable_on_latest) == (1, 1)
