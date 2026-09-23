"""Comparing one day's roster with the segments still running (spec §3.2,
§4.2) — the pure step inside the sync, tested on its own (decided with the
user: the four public methods do not expose segment periods, and
`universe()` arrives in ticket 03).
"""

from __future__ import annotations

from datetime import date

from app.market_data.segments import OpenSegment, SegmentChanges, compare_roster
from tests.fakes import listed

YESTERDAY, TODAY = date(2026, 9, 22), date(2026, 9, 24)


def running(code: str, market: str = "0111", sector33: str = "3700", product: str = "011",
            since: date = date(2026, 1, 5)) -> OpenSegment:
    return OpenSegment(code=code, valid_from=since, market_code=market,
                       product_category=product, sector33=sector33)


def compare(open_segments, roster, known=None) -> SegmentChanges:
    known = {segment.code for segment in open_segments} if known is None else known
    return compare_roster(open_segments, known, roster, day=TODAY, previous_session=YESTERDAY)


def test_an_unchanged_security_changes_nothing() -> None:
    assert compare([running("13010")], [listed("13010")]) == SegmentChanges()


def test_a_move_to_another_market_closes_yesterday_and_opens_today() -> None:
    changes = compare([running("13010", market="0112")], [listed("13010", market="0111")])

    assert changes.closed == [("13010", date(2026, 1, 5), YESTERDAY)]
    assert changes.opened == [running("13010", market="0111", since=TODAY)]


def test_a_change_of_product_category_or_sector_is_a_new_segment_too() -> None:
    changes = compare(
        [running("13010", product="011"), running("13020", sector33="3700")],
        [listed("13010", product="012"), listed("13020", sector33="3650")],
    )

    assert [code for code, _, _ in changes.closed] == ["13010", "13020"]
    assert [segment.code for segment in changes.opened] == ["13010", "13020"]


def test_a_new_name_or_scale_is_not_a_new_segment() -> None:
    changes = compare([running("13010")], [listed("13010", name="新社名", scale="TOPIX Mid400")])

    assert changes == SegmentChanges()


def test_a_first_appearance_opens_a_segment_without_a_warning() -> None:
    changes = compare([], [listed("13010")], known=set())

    assert changes.opened == [running("13010", since=TODAY)]
    assert changes.warnings == []


def test_leaving_the_roster_closes_the_segment_and_opens_nothing() -> None:
    changes = compare([running("13010"), running("13020")], [listed("13020")])

    assert changes.closed == [("13010", date(2026, 1, 5), YESTERDAY)]
    assert changes.opened == []


def test_a_code_that_comes_back_opens_a_segment_and_is_warned_about() -> None:
    changes = compare([], [listed("13010")], known={"13010"})

    assert changes.opened == [running("13010", since=TODAY)]
    assert changes.warnings == ["13010 代码重新出现（2026-09-24）：此前已从名册消失，按新区间记录"]
