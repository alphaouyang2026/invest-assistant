"""A small market for the accounts tests: ten sessions, codes liquid
enough for the universe from the first, TOPIX, and a strategy that holds
and sells on a script — the tests are about accounts, not any strategy."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal

from app.market_data import MarketData, UniverseRule
from app.market_data.jquants import IndexBar, RosterEntry
from app.strategies import Disposition, Plot, Signal
from tests.fakes import FakeJQuants, bar, listed

SESSIONS = [date(2026, 9, 1) + timedelta(days=n) for n in range(10)]
# The universe averages turnover over 20 sessions, a missing one counting as
# nothing: ¥10bn a day is enough from the very first session.
LIQUID = Decimal("10000000000")
TOPIX_ETF = "13060"  # 1306, as `listings` gives it below
ETF_LISTINGS = {TOPIX_ETF: listed(TOPIX_ETF, market="0109", product="014", name="ＴＯＰＩＸ連動型上場投信")}


class Script:
    """A strategy that holds and sells on a script: `plan[day][code]`. It
    buys from Prime common stock unless told another universe rule, and
    reads no reference series unless told some."""

    name = "script"
    warmup_sessions = 1
    plots: tuple[Plot, ...] = ()

    def __init__(self, plan: dict[date, dict[str, Disposition]],
                 universe_rule: UniverseRule = UniverseRule.PRIME_COMMON_STOCK,
                 reference_series: tuple[str, ...] = ()) -> None:
        self.plan = plan
        self.universe_rule = universe_rule
        self.reference_series = reference_series
        self.asked: list[tuple[date, list]] = []
        self.read: set[str] = set()  # every code in the frames it was given

    def evaluate(self, frame, day, holdings):
        self.asked.append((day, sorted((h.code, h.quantity, h.opened_on) for h in holdings)))
        self.read.update(frame.data.index.unique("code"))
        return [Signal(code, disposition, ("scripted",), {}, 0.5) for code, disposition in self.plan.get(day, {}).items()]


def fake_client(prices: dict[str, list[str | None]], *, extra: dict | None = None,
                gone: dict | None = None, listings: Mapping[str, RosterEntry] | None = None) -> FakeJQuants:
    """`prices[code][n]` is the open = high = low = close on SESSIONS[n]; None,
    a halt. `extra[(code, n)]` adds fields to that bar; a code in `gone`
    leaves the roster (and has no bars) from SESSIONS[gone[code]] on. A code
    is Prime common stock unless `listings` has its roster entry (an ETF's,
    say: `ETF_LISTINGS`)."""
    extra, gone, listings = extra or {}, gone or {}, listings or {}
    bars = {day: [bar(code, day, series[n], turnover=LIQUID, **extra.get((code, n), {}))
                  for code, series in prices.items() if n < gone.get(code, len(SESSIONS))]
            for n, day in enumerate(SESSIONS)}
    topix = [IndexBar(day, Decimal("2700"), Decimal("2700"), Decimal("2700"), Decimal("2700")) for day in SESSIONS]

    def roster(day):
        n = SESSIONS.index(day)
        return [listings.get(code) or listed(code) for code in prices if n < gone.get(code, len(SESSIONS))]

    # J-Quants' calendar runs a year ahead of the data: the last session's
    # orders have a next session to go to.
    ahead = [SESSIONS[-1] + timedelta(days=n) for n in (1, 2, 3)]
    return FakeJQuants(SESSIONS + ahead, bars=bars, roster=roster, topix=topix)


def synced(engine, prices: dict[str, list[str | None]], *, extra: dict | None = None,
           gone: dict | None = None, listings: Mapping[str, RosterEntry] | None = None) -> MarketData:
    market = MarketData(engine, fake_client(prices, extra=extra, gone=gone, listings=listings),
                        today=lambda: SESSIONS[-1])
    market.sync()
    return market
