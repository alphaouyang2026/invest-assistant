"""`statistics` (spec §7.4): worked out when read, from the daily net asset
values and the fills. Every expected number below is worked by hand on a
four-session account."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.accounts.statistics import ClosedPosition, statistics

D = [date(2026, 9, n) for n in (1, 2, 3, 4)]


def test_each_figure_on_a_small_account_worked_by_hand() -> None:
    """NAV 100 → 110 → 99 → 108.9: daily returns +10%, −10%, +10%.
    TOPIX 2000 → 2200 over the same sessions: +10% in total."""
    nav = pd.Series([100.0, 110.0, 99.0, 108.9], index=D)
    topix = pd.Series([2000.0, 2100.0, 2050.0, 2200.0], index=D)
    closed = [ClosedPosition("A", D[0], D[2], Decimal("5")), ClosedPosition("B", D[1], D[3], Decimal("-1"))]

    figures = statistics(nav, topix, closed, bought=Decimal("60"), sold=Decimal("40"))

    assert figures.total_return == pytest.approx(0.089)
    assert figures.annualised_return == pytest.approx(1.089 ** (245 / 3) - 1)
    assert figures.max_drawdown == pytest.approx(0.1)                     # 110 → 99
    returns = [0.1, -0.1, 0.1]
    mean, std = sum(returns) / 3, math.sqrt(sum((r - 1 / 30) ** 2 for r in returns) / 2)
    assert figures.sharpe == pytest.approx(mean / std * math.sqrt(245))
    assert figures.win_rate == pytest.approx(0.5)                          # A made money, B lost
    assert figures.average_holding_sessions == pytest.approx(2.0)          # A: D1, D2; B: D2, D3
    assert figures.annual_turnover == pytest.approx((60 + 40) / 2 / nav.mean() * 245 / 3)
    assert figures.excess_annualised_return == pytest.approx(
        (1.089 ** (245 / 3) - 1) - (1.1 ** (245 / 3) - 1))
    assert list(figures.nav_curve) == pytest.approx([1.0, 1.1, 0.99, 1.089])
    assert list(figures.topix_curve) == pytest.approx([1.0, 1.05, 1.025, 1.1])
