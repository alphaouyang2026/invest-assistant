"""`MarketData.instruments` (spec A.1): names and current market for the
signal page, and the search behind `GET /api/instruments?q=`."""

from __future__ import annotations

from datetime import date

from app.market_data import Instrument, MarketData
from tests.fakes import FakeJQuants, bar, listed

D1, D2 = date(2026, 9, 18), date(2026, 9, 22)
PRIME, GROWTH = "0111", "0113"


def synced(migrated_database, roster) -> MarketData:
    codes = sorted({entry.code for day in (D1, D2) for entry in roster(day)})
    client = FakeJQuants([D1, D2], bars={day: [bar(code, day) for code in codes] for day in (D1, D2)}, roster=roster)
    market = MarketData(migrated_database, client, today=lambda: D2)
    market.sync()
    return market


def test_search_matches_a_code_prefix_or_part_of_either_name(migrated_database) -> None:
    roster = [
        listed("72030", PRIME, name="トヨタ自動車"),
        listed("67580", PRIME, name="ソニーグループ"),
        listed("72670", PRIME, name="本田技研工業"),
    ]
    market = synced(migrated_database, lambda day: roster)

    assert [i.code for i in market.instruments(query="72")] == ["72030", "72670"]
    assert [i.code for i in market.instruments(query="ソニー")] == ["67580"]
    assert [i.code for i in market.instruments(query="company 7267")] == ["72670"]  # name_en, any case
    assert market.instruments(query="トヨタ") == [Instrument("72030", "トヨタ自動車", "Company 72030", PRIME)]
    assert market.instruments(query="TOPIX") == []  # an index, not a security to trade


def test_by_code_with_the_market_it_is_in_now_or_none_once_it_has_left(migrated_database) -> None:
    def roster(day):
        return [listed("13010", PRIME if day == D1 else GROWTH)] + ([listed("13020", PRIME)] if day == D1 else [])

    market = synced(migrated_database, roster)

    assert [(i.code, i.market) for i in market.instruments(codes=["13020", "13010"])] == [
        ("13010", GROWTH), ("13020", None),
    ]
