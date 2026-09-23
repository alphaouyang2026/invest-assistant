"""An in-memory J-Quants, and builders for the records it serves.

The market data tests run the production sync against this through the
same `JQuantsClient` interface the HTTP adapter implements; only the
network is gone. Rate limiting, 429s and pages are the HTTP adapter's
business and are tested there (test_jquants_http.py).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal

from app.market_data.jquants import BarRecord, CalendarDay, IndexBar, JQuantsError, RosterEntry


def bar(code: str, day: date, close: str | None = "100", **fields) -> BarRecord:
    """A complete, ordinary bar: flat OHLC at `close`, nothing unusual."""
    price = None if close is None else Decimal(close)
    values = dict(
        code=code, date=day,
        open=price, high=price, low=price, close=price,
        volume=Decimal("1000"), turnover=Decimal("100000"),
        adjustment_factor=Decimal("1"), ex_rights_type=None,
        upper_limit_hit=False, lower_limit_hit=False,
        adjusted_close=price,
    )
    values.update(fields)
    return BarRecord(**values)


def listed(code: str, market: str = "0111", *, name: str | None = None, sector33: str = "3700",
           product: str = "011", scale: str = "TOPIX Small 1") -> RosterEntry:
    return RosterEntry(
        code=code, name=name or f"会社{code}", name_en=f"Company {code}", scale_category=scale,
        market_code=market, product_category=product, sector33=sector33,
    )


class FakeJQuants:
    """Serves whatever the test put in it.

    - `sessions` become the calendar (every other date in between is closed);
    - `bars[day]` is what `daily_bars_on(day)` returns — empty when absent;
    - `roster` is either a fixed list or a function of the date;
    - `history[code]` is what `daily_bars_for` returns, J-Quants' view *today*
      (with `AdjC` rewritten by every later split), which is not what the
      per-date bars carried on their own day;
    - `fail_on` makes `daily_bars_on` raise for those dates — once each, so
      the next run gets through, as an interrupted-then-rerun sync would.
    """

    def __init__(
        self,
        sessions: Iterable[date],
        *,
        bars: dict[date, list[BarRecord]] | None = None,
        roster: list[RosterEntry] | Callable[[date], list[RosterEntry]] | None = None,
        topix: list[IndexBar] | None = None,
        history: dict[str, list[BarRecord]] | None = None,
        fail_on: Iterable[date] = (),
    ) -> None:
        self.sessions = sorted(sessions)
        self.bars = bars if bars is not None else {}
        self.roster = roster if roster is not None else []
        self.topix_bars = topix if topix is not None else []
        self.history = history if history is not None else {}
        self.fail_on = set(fail_on)
        self.bar_requests: list[date] = []
        self.history_requests: list[tuple[str, date, date]] = []

    def daily_bars_on(self, day: date) -> list[BarRecord]:
        self.bar_requests.append(day)
        if day in self.fail_on:
            self.fail_on.discard(day)
            raise JQuantsError(f"scripted failure on {day}")
        return list(self.bars.get(day, []))

    def daily_bars_for(self, code: str, start: date, end: date) -> list[BarRecord]:
        self.history_requests.append((code, start, end))
        return [row for row in self.history.get(code, []) if start <= row.date <= end]

    def roster_on(self, day: date) -> list[RosterEntry]:
        return list(self.roster(day) if callable(self.roster) else self.roster)

    def calendar(self) -> list[CalendarDay]:
        if not self.sessions:
            return []
        open_days = set(self.sessions)
        first, last = self.sessions[0], self.sessions[-1]
        return [
            CalendarDay(day, 1 if day in open_days else 0)
            for day in (date.fromordinal(n) for n in range(first.toordinal(), last.toordinal() + 1))
        ]

    def topix(self, start: date, end: date) -> list[IndexBar]:
        return [row for row in self.topix_bars if start <= row.date <= end]
