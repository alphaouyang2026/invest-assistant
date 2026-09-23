"""`MarketData.calendar()`: the trading calendar, in memory after one read.

Open days are HolDiv 1 (full) and 2 (half); 0 and 3 are closed.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.market_data import MarketData
from app.market_data.jquants import CalendarDay

FRI, SAT, MON, TUE, WED = date(2026, 9, 18), date(2026, 9, 19), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)


class CalendarOnly:
    def calendar(self):
        return [CalendarDay(FRI, 1), CalendarDay(SAT, 0), CalendarDay(MON, 3), CalendarDay(TUE, 2), CalendarDay(WED, 1)]

    def daily_bars_on(self, day):
        return []

    def roster_on(self, day):
        return []

    def topix(self, start, end):
        return []


@pytest.fixture
def calendar(migrated_database):
    market = MarketData(migrated_database, CalendarOnly(), today=lambda: date(2026, 9, 17))
    market.sync()
    return market.calendar()


def test_open_days_are_full_and_half_days(calendar) -> None:
    assert calendar.sessions() == [FRI, TUE, WED]
    assert [calendar.is_session(day) for day in (FRI, SAT, MON, TUE)] == [True, False, False, True]


def test_next_and_prev_skip_closed_days_from_any_date(calendar) -> None:
    assert calendar.next(FRI) == TUE
    assert calendar.next(SAT) == TUE
    assert calendar.prev(WED) == TUE
    assert calendar.prev(MON) == FRI


def test_offset_counts_sessions(calendar) -> None:
    assert calendar.offset(FRI, 2) == WED
    assert calendar.offset(WED, -2) == FRI
    assert calendar.offset(TUE, 0) == TUE


def test_stepping_past_the_known_calendar_is_an_error_not_a_guess(calendar) -> None:
    with pytest.raises(LookupError):
        calendar.next(WED)
    with pytest.raises(LookupError):
        calendar.offset(FRI, -1)
