"""`Calendar` — the trading calendar as `MarketData.calendar()` returns it.

Pure and in memory: built from one read of `trading_calendar`, so callers
can step through sessions in a loop without touching the database.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from datetime import date


class Calendar:
    def __init__(self, sessions: Iterable[date]) -> None:
        self._sessions = sorted(sessions)
        self._positions = {day: index for index, day in enumerate(self._sessions)}

    def sessions(self) -> list[date]:
        """Every open day known, oldest first."""
        return list(self._sessions)

    def is_session(self, day: date) -> bool:
        return day in self._positions

    def next(self, day: date) -> date:
        """The first session after `day`, which need not be a session."""
        return self._at(bisect_right(self._sessions, day), f"{day} 之后没有已知的开市日")

    def prev(self, day: date) -> date:
        """The last session before `day`, which need not be a session."""
        return self._at(bisect_left(self._sessions, day) - 1, f"{day} 之前没有已知的开市日")

    def offset(self, day: date, sessions: int) -> date:
        """The session `sessions` open days from the session `day`."""
        if day not in self._positions:
            raise LookupError(f"{day} 不是开市日")
        return self._at(self._positions[day] + sessions, f"{day} 偏移 {sessions} 个开市日超出了已知日历")

    def _at(self, index: int, problem: str) -> date:
        if not 0 <= index < len(self._sessions):
            raise LookupError(problem)
        return self._sessions[index]
