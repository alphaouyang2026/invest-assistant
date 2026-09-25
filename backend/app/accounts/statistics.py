"""An account's figures (spec §7.4), worked out when read from its daily
net asset values and its fills. Pure.

A year is 245 sessions, for the annualised figures as for the Sharpe
ratio. Dividends and tax are not in any of them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

SESSIONS_A_YEAR = 245


@dataclass(frozen=True)
class ClosedPosition:
    """A position from its first shares to its last: sold or settled."""

    code: str
    opened_on: date
    closed_on: date     # the session its last shares went
    profit: Decimal     # what it brought in less what it cost, fees included


@dataclass(frozen=True)
class Figures:
    total_return: float
    annualised_return: float | None
    max_drawdown: float
    sharpe: float | None                  # None without a spread of returns to divide by
    win_rate: float | None                # None before any position has closed
    average_holding_sessions: float | None
    annual_turnover: float | None
    excess_annualised_return: float | None  # over TOPIX, the same sessions
    nav_curve: pd.Series                  # both start at 1
    topix_curve: pd.Series


def statistics(nav: pd.Series, topix: pd.Series, closed: Sequence[ClosedPosition], *,
               bought: Decimal, sold: Decimal) -> Figures:
    """`nav` is the net asset value at each session's close, from the start;
    `topix` its close on the same sessions; `bought` and `sold` the amounts
    traded over them."""
    returns = nav.pct_change().dropna()
    periods = len(returns)
    total = float(nav.iloc[-1] / nav.iloc[0] - 1)

    def annualised(growth: float) -> float | None:
        return None if periods == 0 else (1 + growth) ** (SESSIONS_A_YEAR / periods) - 1

    spread = returns.std(ddof=1) if periods > 1 else 0.0
    sharpe = None if not spread else float(returns.mean() / spread * math.sqrt(SESSIONS_A_YEAR))
    drawdown = float((1 - nav / nav.cummax()).max())

    sessions = list(nav.index)
    held = [sum(1 for day in sessions if p.opened_on <= day < p.closed_on) for p in closed]
    mine, theirs = annualised(total), annualised(float(topix.iloc[-1] / topix.iloc[0] - 1))
    return Figures(
        total_return=total,
        annualised_return=mine,
        max_drawdown=drawdown,
        sharpe=sharpe,
        win_rate=None if not closed else sum(1 for p in closed if p.profit > 0) / len(closed),
        average_holding_sessions=None if not closed else sum(held) / len(held),
        annual_turnover=None if periods == 0 else
        float((bought + sold) / 2) / float(nav.mean()) * SESSIONS_A_YEAR / periods,
        excess_annualised_return=None if mine is None or theirs is None else mine - theirs,
        nav_curve=nav / nav.iloc[0],
        topix_curve=topix / topix.iloc[0],
    )
