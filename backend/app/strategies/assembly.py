"""`entry_candidates` and `history` (spec A.3): not a seam, but the one
place that knows how a strategy is fed — take the universe, read back as
far as the warm-up needs, evaluate, add names. The signal page and the
security page call these; the accounts module reads its own long frame
and calls `evaluate` directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.market_data import CLOSE, Instrument, MarketData, MarketFrame
from app.strategies.base import Disposition, Signal, Strategy


@dataclass(frozen=True)
class Candidate:
    signal: Signal
    instrument: Instrument


def entry_candidates(market: MarketData, strategy: Strategy, day: date) -> list[Candidate]:
    """Who can be held from `day`'s close, seen from holding nothing:
    highest priority first, then by code."""
    universe = market.universe(day)
    if not universe:
        return []
    frame = market.read(universe, _warm_up_start(market, strategy, day), day)
    holdable = [signal for signal in strategy.evaluate(frame, day, []) if signal.disposition is Disposition.HOLD]
    names = {instrument.code: instrument for instrument in market.instruments(codes=[s.code for s in holdable])}
    holdable.sort(key=lambda signal: (-(signal.priority or 0.0), signal.code))
    return [Candidate(signal, names[signal.code]) for signal in holdable]


@dataclass(frozen=True)
class SecurityHistory:
    frame: MarketFrame        # its bars from `start` to `end`
    indicators: pd.DataFrame  # a row per session, a column per line the strategy plots
    entries: list[date]       # sessions it could have been held from, holding nothing


def history(market: MarketData, strategy: Strategy, code: str, start: date, end: date) -> SecurityHistory:
    """What the security page draws: the strategy asked about each session
    in turn — the same `evaluate`, no second way in (spec A.3)."""
    frame = market.read([code], _warm_up_start(market, strategy, start), end)
    days = [day for day in frame.wide(CLOSE).index if start <= day <= end]
    names = [plot.indicator for plot in strategy.plots]
    rows, entries = {}, []
    for day in days:
        mine = [signal for signal in strategy.evaluate(frame, day, []) if signal.code == code]
        rows[day] = {name: mine[0].indicators.get(name) if mine else None for name in names}
        if mine and mine[0].disposition is Disposition.HOLD:
            entries.append(day)
    shown = frame.data[[start <= day <= end for day in frame.data.index.get_level_values("date")]]
    return SecurityHistory(MarketFrame(shown), pd.DataFrame.from_dict(rows, orient="index", columns=names), entries)


def _warm_up_start(market: MarketData, strategy: Strategy, day: date) -> date:
    """The earliest of the `warmup_sessions` sessions up to `day` (which
    need not be a session itself), so the first day asked about has its
    warm-up; as far back as the calendar goes if it is shorter."""
    sessions = [session for session in market.calendar().sessions() if session <= day]
    if not sessions:
        return day
    return sessions[max(0, len(sessions) - strategy.warmup_sessions)]
