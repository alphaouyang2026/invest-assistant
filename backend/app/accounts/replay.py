"""A whole range replayed on an isolated ledger (spec §7.5, ADR-0006): each
session is `replay_day`, the paper accounts' own; the records are numbered
here, not stored. A research run and a model experiment's replays both
come through it, and read it back a session at a time through
`Replay.days` — which order was planned when, which took effect at which
open, and what a close's plan aims to hold — without working out the
ledger's rules themselves."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import pandas as pd

from app.accounts.accounts import Prices, replay_day
from app.accounts.ledger import Ledger, Position
from app.accounts.planning import PortfolioRules
from app.accounts.records import BUY, EXPIRED, FILLED, SELL, SKIPPED, SPLIT_ROUNDING, Record
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
class ReplayDay:
    """One replayed session, as the replay's ledger tells it."""

    point: NavPoint                  # its close
    cash: Decimal                    # at the close
    positions: dict[str, Position]   # held at the close
    planned: list[Record]            # buys and sells planned at the close, as they ended, in the order written
    # What took effect at its open: orders filled or expired there, a buy a
    # split rounded to nothing, split adjustments and delisting settlements.
    opened: list[Record]

    @property
    def day(self) -> date:
        return self.point.day

    def given_up(self) -> list[Record]:
        """Orders planned at the close that were never placed for the next
        open: the portfolio rules gave up on them then (spec §7.2)."""
        return [order for order in self.planned if _given_up(order)]

    def target(self) -> dict[str, int]:
        """The holdings the close's plan aims at: those held at the close,
        less every code it sells, plus what it buys — the orders placed, as
        planned, whatever became of them at the open. A buy a split rounded
        to nothing aims at nothing."""
        target = {code: position.quantity for code, position in self.positions.items()}
        for order in self.planned:
            if _given_up(order):
                continue
            if order.kind == SELL:
                target.pop(order.code, None)
            else:
                target[order.code] = target.get(order.code, 0) + order.planned_quantity
        return {code: quantity for code, quantity in target.items() if quantity}


@dataclass(frozen=True)
class Replay:
    ledger: Ledger           # as it ended; records numbered 1, 2, … in the order written
    points: list[NavPoint]   # one a session, oldest first
    warnings: list[str]      # as met, repeats kept

    def days(self) -> list[ReplayDay]:
        """Each replayed session, oldest first: its close, the orders planned
        then and what took effect at its open."""
        planned: dict[date, list[Record]] = defaultdict(list)
        opened: dict[date, list[Record]] = defaultdict(list)
        for record in self.ledger.records:
            if record.kind in (BUY, SELL):
                planned[record.signal_date].append(record)
                if record.status in (FILLED, EXPIRED) or record.outcome_reason == SPLIT_ROUNDING:
                    opened[record.execution_date].append(record)
            else:  # a split adjustment or a delisting settlement, on its day
                opened[record.execution_date].append(record)
        closes = self.ledger.by_session([point.day for point in self.points])
        return [ReplayDay(point, cash, positions, planned[day], opened[day])
                for (day, cash, positions), point in zip(closes, self.points, strict=True)]


def _given_up(order: Record) -> bool:
    """Skipped when planned, not at the open: the only order skipped at the
    open is a buy a split rounded to nothing, which had been placed."""
    return order.status == SKIPPED and order.outcome_reason != SPLIT_ROUNDING


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
