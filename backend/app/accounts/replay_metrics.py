"""A replay's report figures. Pure — a replay, its NAV points and records
in, no database. Dividends and tax are in none of them.

- What it ended with (spec §7.5): its holdings and pending orders, its
  return against TOPIX's, drawdown, trades, fees, cash and profit — a
  research run's result and each model experiment replay's alike.
- Spec §7.4's statistics over it.
- Beyond them (06a): how many orders filled and why the rest did not, cash
  held, returns by year and by range, turnover, and order size against
  ADV20.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from app.accounts.ledger import Position
from app.accounts.records import BUY, EXPIRED, FILLED, SELL, SKIPPED, Record, record_json
from app.accounts.replay import NavPoint, Replay
from app.accounts.statistics import SESSIONS_A_YEAR, Figures, statistics


@dataclass(frozen=True)
class FillRate:
    """Orders placed for an open: filled or expired there. Skipped ones
    were never placed and are counted apart; pending ones are neither."""

    filled: int
    expired: int
    rate: float | None               # filled ÷ (filled + expired); None with neither
    expired_reasons: dict[str, int]  # untradable, limit_up_open, limit_down_open, insufficient_cash, delisted
    skipped_reasons: dict[str, int]  # lot_unaffordable, insufficient_cash, adv20_cap


@dataclass(frozen=True)
class PeriodReturn:
    start: date            # the period's first session with a NAV point
    end: date              # its last
    sessions: int
    net_return: float      # costs included: from the close before `start` (the initial capital if none)
    topix_return: float    # TOPIX over the same closes (from the first session's if none before)


@dataclass(frozen=True)
class Adv20Usage:
    """Filled orders' amounts over the code's ADV20 on the signal day."""

    orders: int            # filled buys and sells with an ADV20 to divide by
    median: float | None
    p95: float | None
    max: float | None
    over_cap: int          # above the cap; 0 without one
    without_adv20: int     # filled, but no ADV20 known (or none at all)


def holding_lines(positions: Iterable[Position], closes: Mapping[str, Decimal]) -> list[dict]:
    """Each position valued at `closes`, JSON-ready, in the order given:
    its shares, the session it opened, its cost (fees included), the close
    and its value."""
    return [{"code": p.code, "quantity": p.quantity, "opened_on": p.opened_on.isoformat(), "cost": float(p.cost),
             "close": float(closes[p.code]), "value": float(p.quantity * closes[p.code])} for p in positions]


def end_state(replay: Replay, closes: Mapping[str, Decimal]) -> dict:
    """What `replay` ended with, JSON-ready (spec §7.5): its holdings valued
    at `closes` (the last day's) in the ledger's order, its pending orders
    and warnings, its return and TOPIX's from the first close to the last,
    its deepest drawdown, how many orders filled, the fees, the cash, and
    its profit — unrealised on what it holds, realised on the rest."""
    ledger, points = replay.ledger, replay.points
    last = points[-1]
    unrealised = sum((p.quantity * closes[p.code] - p.cost for p in ledger.positions.values()), Decimal(0))
    total, baseline = last.nav_curve - 1, last.topix_curve - 1
    return {"holdings": holding_lines(ledger.positions.values(), closes),
            "pending": [record_json(r) for r in ledger.pending], "warnings": sorted(set(replay.warnings)),
            "total_return": total, "topix_return": baseline, "excess_return": total - baseline,
            "max_drawdown": max(p.drawdown for p in points),
            "trades": sum(r.status == FILLED and r.kind in (BUY, SELL) for r in ledger.records),
            "fees": float(sum((r.fees for r in ledger.records), Decimal(0))),
            "cash": float(ledger.cash), "unrealised_pnl": float(unrealised),
            "realised_pnl": float(last.nav - ledger.initial_cash - unrealised)}


def replay_statistics(replay: Replay) -> Figures:
    """Spec §7.4's figures over `replay`: its closes' NAV against TOPIX's,
    the positions it closed and what it traded."""
    nav = pd.Series([float(p.nav) for p in replay.points], index=[p.day for p in replay.points])
    topix = pd.Series([p.topix_curve for p in replay.points], index=nav.index)
    amounts = traded(replay.ledger.records)
    return statistics(nav, topix, replay.ledger.closed, bought=amounts[BUY], sold=amounts[SELL])


def traded(records: Iterable[Record]) -> dict[str, Decimal]:
    """What the filled buys and the filled sells came to, slippage included."""
    records = list(records)
    return {kind: sum((r.fill_price * r.filled_quantity for r in records if r.kind == kind and r.status == FILLED),
                      Decimal(0)) for kind in (BUY, SELL)}


def fill_rate(records: Iterable[Record], *, kind: str | None = None) -> FillRate:
    """Over buys and sells, or one `kind` of them."""
    orders = [r for r in records if r.kind in ((kind,) if kind else (BUY, SELL))]
    filled = sum(r.status == FILLED for r in orders)
    expired = Counter(r.outcome_reason for r in orders if r.status == EXPIRED)
    skipped = Counter(r.outcome_reason for r in orders if r.status == SKIPPED)
    tried = filled + expired.total()
    return FillRate(filled, expired.total(), filled / tried if tried else None, dict(sorted(expired.items())),
                    dict(sorted(skipped.items())))


def average_cash_share(points: Sequence[NavPoint]) -> float | None:
    """Cash over the NAV at each close, averaged over the sessions."""
    if not points:
        return None
    return float(sum((p.cash / p.nav for p in points), Decimal(0)) / len(points))


def period_returns(points: Sequence[NavPoint], ranges: Sequence[tuple[date, date]]) -> list[PeriodReturn | None]:
    """Each range's return, both ends included; None for one with no point
    in it. Ranges may overlap or leave gaps (a fold's test segment, a year)."""
    returns = []
    for start, end in ranges:
        inside = [p for p in points if start <= p.day <= end]
        if not inside:
            returns.append(None)
            continue
        before = [p for p in points if p.day < start]
        nav_base, topix_base = (before[-1].nav_curve, before[-1].topix_curve) if before else (1.0, 1.0)
        returns.append(PeriodReturn(inside[0].day, inside[-1].day, len(inside),
                                    inside[-1].nav_curve / nav_base - 1, inside[-1].topix_curve / topix_base - 1))
    return returns


def yearly_returns(points: Sequence[NavPoint]) -> dict[int, PeriodReturn]:
    """Each calendar year with a point, from the previous year's last close."""
    years = sorted({p.day.year for p in points})
    found = period_returns(points, [(date(year, 1, 1), date(year, 12, 31)) for year in years])
    return dict(zip(years, found))


def annual_turnover(points: Sequence[NavPoint], records: Iterable[Record]) -> float | None:
    """(Bought + sold) ÷ 2 ÷ the average NAV, over a year of 245 sessions —
    spec §7.4's turnover. None over a single session."""
    periods = len(points) - 1
    if periods <= 0:
        return None
    amounts = traded(records)
    average = sum((p.nav for p in points), Decimal(0)) / len(points)
    return float((amounts[BUY] + amounts[SELL]) / 2) / float(average) * SESSIONS_A_YEAR / periods


def adv20_usage(records: Iterable[Record], adv20: Mapping[tuple[date, str], Decimal], *,
                cap: Decimal | None = None) -> Adv20Usage:
    """`adv20` holds each order's ADV20 by (signal date, code) — what the
    cap was worked out from; the amount is what filled, slippage included,
    so a buy cut to the cap at the close can still come out a little over."""
    shares, missing = [], 0
    for r in records:
        if r.kind not in (BUY, SELL) or r.status != FILLED:
            continue
        known = adv20.get((r.signal_date, r.code))
        if not known:
            missing += 1
            continue
        shares.append(r.fill_price * r.filled_quantity / known)
    if not shares:
        return Adv20Usage(0, None, None, None, 0, missing)
    spread = pd.Series([float(share) for share in shares])
    return Adv20Usage(len(shares), float(spread.median()), float(spread.quantile(0.95)), float(spread.max()),
                      0 if cap is None else sum(share > cap for share in shares), missing)
