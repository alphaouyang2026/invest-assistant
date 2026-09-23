"""An interrupted sync, rerun, ends where an uninterrupted one does (spec
§4.2): no progress is recorded, so this is the whole of the resume story.

The one test that looks at the tables directly (agreed with the user):
"row for row the same" is the claim, and none of the public methods show
segment periods or instruments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.config import Settings
from app.market_data import MarketData
from app.market_data.jquants import IndexBar, JQuantsError
from app.migrate import upgrade_to_head
from tests.fakes import FakeJQuants, bar, listed

SESSIONS = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
TODAY = SESSIONS[-1]
TABLES = ("instruments", "segment_periods", "daily_bars", "trading_calendar")


def a_busy_week() -> dict:
    """Something happening every day: a split, a market move, a departure."""
    d1, d2, d3, d4, d5 = SESSIONS
    bars = {
        day: [bar("13010", day, "1000"), bar("13020", day, "200"), bar("13030", day, "50")]
        for day in SESSIONS
    }
    bars[d3] = [bar("13010", d3, "505", adjustment_factor=Decimal("0.5"), ex_rights_type=1),
                bar("13020", d3, "210"), bar("13030", d3, "51")]
    bars[d5] = [bar("13010", d5, "510"), bar("13020", d5, "220")]  # 13030 is gone

    def roster(day: date):
        return [
            listed("13010", name="旧社名" if day < d4 else "新社名"),
            listed("13020", market="0112" if day < d4 else "0111"),
            *([listed("13030")] if day < d5 else []),
        ]

    topix = [IndexBar(day, Decimal("2700"), Decimal("2710"), Decimal("2690"), Decimal("2705")) for day in SESSIONS]
    return dict(bars=bars, roster=roster, topix=topix)


def fresh_database(tmp_path, monkeypatch, name: str):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / name))
    upgrade_to_head()
    return create_engine(Settings(_env_file=None).database_url)


def dump(engine) -> dict[str, list[tuple]]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"select * from {table} order by 1, 2")).all()
            for table in TABLES
        }


def test_a_sync_interrupted_midway_and_rerun_matches_one_that_ran_straight_through(tmp_path, monkeypatch) -> None:
    straight = fresh_database(tmp_path, monkeypatch, "straight.db")
    MarketData(straight, FakeJQuants(SESSIONS, **a_busy_week()), today=lambda: TODAY).sync()

    interrupted = fresh_database(tmp_path, monkeypatch, "interrupted.db")
    client = FakeJQuants(SESSIONS, **a_busy_week(), fail_on=[SESSIONS[3]])
    with pytest.raises(JQuantsError):
        MarketData(interrupted, client, today=lambda: TODAY).sync()
    MarketData(interrupted, client, today=lambda: TODAY).sync()

    expected, actual = dump(straight), dump(interrupted)
    assert all(expected[table] for table in TABLES)  # the comparison is not vacuous
    for table in TABLES:
        assert actual[table] == expected[table], table
