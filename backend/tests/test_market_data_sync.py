"""Syncing: what `MarketData.sync` leaves behind, seen through `read`,
`calendar` and `overview` — the market data module's public face.

Backfill and the daily sync are the same function; the only difference is
where the database's own maximum date leaves off.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.market_data.jquants import IndexBar

from app.market_data import MarketData
from tests.fakes import FakeJQuants, bar, listed

TODAY = date(2026, 9, 24)


@pytest.fixture
def market_for(migrated_database):
    def build(client: FakeJQuants, today: date = TODAY) -> MarketData:
        return MarketData(migrated_database, client, today=lambda: today)

    return build


def everyone_trades(sessions, codes=("13010",)) -> dict:
    return {day: [bar(code, day) for code in codes] for day in sessions}


def test_an_empty_database_is_backfilled_from_the_first_session_five_years_back(market_for) -> None:
    sessions = [date(2021, 9, 22), date(2021, 9, 24), date(2021, 9, 27), date(2026, 9, 24)]
    client = FakeJQuants(sessions, bars=everyone_trades(sessions), roster=[listed("13010")])

    market_for(client).sync()

    frame = market_for(client).read(["13010"], date(2021, 1, 1), TODAY)
    assert frame.dates("13010") == [date(2021, 9, 24), date(2021, 9, 27), date(2026, 9, 24)]


def test_a_later_sync_fetches_only_the_sessions_after_the_latest_stored_date(market_for) -> None:
    sessions = [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)]
    client = FakeJQuants(sessions, bars=everyone_trades(sessions), roster=[listed("13010")])
    market_for(client, today=date(2026, 9, 18)).sync()
    client.bar_requests.clear()

    market_for(client, today=date(2026, 9, 24)).sync()

    assert client.bar_requests == [date(2026, 9, 22), date(2026, 9, 24)]
    assert market_for(client).read(["13010"], date(2026, 9, 1), TODAY).dates("13010") == sessions


def test_an_empty_answer_for_today_means_the_data_is_not_out_yet(market_for) -> None:
    sessions = [date(2026, 9, 22), date(2026, 9, 24)]
    client = FakeJQuants(sessions, bars=everyone_trades(sessions[:1]), roster=[listed("13010")])

    report = market_for(client).sync()

    assert report.not_published_yet
    assert "当天数据未出" in report.warnings[-1]
    assert market_for(client).read(None, date(2026, 9, 1), TODAY).dates("13010") == [date(2026, 9, 22)]


def test_once_todays_data_is_out_a_rerun_picks_it_up(market_for) -> None:
    sessions = [date(2026, 9, 22), date(2026, 9, 24)]
    client = FakeJQuants(sessions, bars=everyone_trades(sessions[:1]), roster=[listed("13010")])
    market_for(client).sync()

    client.bars[TODAY] = [bar("13010", TODAY)]
    report = market_for(client).sync()

    assert not report.not_published_yet
    assert market_for(client).read(None, date(2026, 9, 1), TODAY).dates("13010") == sessions


def test_an_empty_past_session_is_warned_about_and_the_sync_goes_on(market_for) -> None:
    sessions = [date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)]
    bars = everyone_trades([date(2026, 9, 18), date(2026, 9, 24)])
    client = FakeJQuants(sessions, bars=bars, roster=[listed("13010")])

    report = market_for(client).sync()

    assert not report.not_published_yet
    assert any("2026-09-22" in warning for warning in report.warnings)
    assert market_for(client).read(None, date(2026, 9, 1), TODAY).dates("13010") == [
        date(2026, 9, 18), date(2026, 9, 24),
    ]


def test_a_code_back_on_the_roster_after_leaving_it_is_reported(market_for) -> None:
    sessions = [date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)]
    rosters = {
        date(2026, 9, 18): [listed("13010"), listed("13020")],
        date(2026, 9, 22): [listed("13020")],
        date(2026, 9, 24): [listed("13010"), listed("13020")],
    }
    client = FakeJQuants(sessions, bars=everyone_trades(sessions, ("13020",)), roster=rosters.__getitem__)

    report = market_for(client).sync()

    assert [warning for warning in report.warnings if "代码重新出现" in warning] == [
        "13010 代码重新出现（2026-09-24）：此前已从名册消失，按新区间记录",
    ]


def topix_on(day: date, close: str) -> IndexBar:
    return IndexBar(day, Decimal(close), Decimal(close), Decimal(close), Decimal(close))


def test_topix_is_synced_over_the_same_sessions_and_read_only_by_name(market_for) -> None:
    sessions = [date(2026, 9, 22), date(2026, 9, 24)]
    client = FakeJQuants(
        sessions, bars=everyone_trades(sessions), roster=[listed("13010")],
        topix=[topix_on(date(2026, 9, 18), "2600"), topix_on(date(2026, 9, 22), "2700"),
               topix_on(date(2026, 9, 24), "2710.5")],
    )

    market_for(client).sync()

    market = market_for(client)
    assert market.read(["TOPIX"], date(2026, 9, 1), TODAY).closes()["TOPIX"].tolist() == [2700.0, 2710.5]
    assert market.read(None, date(2026, 9, 1), TODAY).closes().columns.tolist() == ["13010"]


def test_progress_is_reported_after_each_session(market_for) -> None:
    sessions = [date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)]
    client = FakeJQuants(sessions, bars=everyone_trades(sessions), roster=[listed("13010")])
    seen = []

    market_for(client).sync(on_progress=seen.append)

    assert [(p.sessions_done, p.sessions_total, p.current_session) for p in seen] == [
        (1, 3, date(2026, 9, 18)), (2, 3, date(2026, 9, 22)), (3, 3, date(2026, 9, 24)),
    ]
