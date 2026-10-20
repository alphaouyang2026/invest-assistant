"""A whole range replayed on an isolated ledger (spec §7.5, ADR-0006): each
session is `replay_day`, the paper accounts' own; the records are numbered
here, not stored. A research run and a model experiment's replays both
come through it."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import pandas as pd

from app.accounts.accounts import Prices, replay_day
from app.accounts.ledger import Ledger
from app.accounts.planning import PortfolioRules
from app.accounts.session import Costs
from app.market_data import Calendar
from app.strategies import Strategy


@dataclass(frozen=True)
class NavPoint:
    """One session's close."""

    day: date
    nav: Decimal
    cash: Decimal
    nav_curve: float    # the NAV over the initial capital
    topix_curve: float  # TOPIX over its close on the first session
    drawdown: float     # below the highest NAV so far, the initial capital included

    def as_json(self) -> dict:
        """As a research run stores it (without the cash)."""
        return {"date": self.day.isoformat(), "nav": float(self.nav), "nav_curve": self.nav_curve,
                "topix_curve": self.topix_curve, "drawdown": self.drawdown}


@dataclass(frozen=True)
class Replay:
    ledger: Ledger           # as it ended; records numbered 1, 2, … in the order written
    points: list[NavPoint]   # one a session, oldest first
    warnings: list[str]      # as met, repeats kept


def replay_range(prices: Prices, strategy: Strategy, universes: Mapping[date, list[str]], days: Sequence[date],
                 calendar: Calendar, rules: PortfolioRules, costs: Costs, initial: Decimal, topix: pd.Series, *,
                 on_session: Callable[[int, date], None] | None = None) -> Replay:
    """From `initial` cash, no holdings and no orders, through `days` (each
    a session, oldest first): a signal at a day's close fills at the next
    session's open at the earliest; the last day's orders are left pending.
    `topix` holds TOPIX's execution close on each day; `on_session` is told
    how many days are done after each."""
    ledger, points, warnings = Ledger(initial), [], []
    serial, peak = 0, initial
    for done, day in enumerate(days, 1):
        changed, found = replay_day(ledger, prices, strategy, universes, day, calendar.next(day), rules, costs)
        warnings.extend(found)
        # Accounts._store's last-write-wins rule, with ids local to this replay.
        final = {r.id: r for r in changed if r.id is not None}
        stored = []
        for r in changed:
            if r.id is None:
                serial += 1
                stored.append(replace(r, id=serial))
            elif final[r.id] is r:
                stored.append(r)
        ledger = ledger.apply(stored)
        closes = prices.closes(day, ledger.positions)
        nav = ledger.cash + sum((p.quantity * closes[p.code] for p in ledger.positions.values()), Decimal(0))
        peak = max(peak, nav)
        points.append(NavPoint(day, nav, ledger.cash, float(nav / initial), float(topix[day] / topix[days[0]]),
                               float(1 - nav / peak)))
        if on_session is not None:
            on_session(done, day)
    return Replay(ledger, points, warnings)
