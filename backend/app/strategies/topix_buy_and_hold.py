"""TOPIX ETF buy-and-hold v1: the control group for the TOPIX ETF strategies
(.scratch/topix-etf-strategies/spec.md).

Its universe is 1306 alone. Whatever can be judged — a bar that day, not
untradable — can be held, and a holding is never sold, so an account buys
1306 once and keeps it: filled, split and valued by the same rules as any
other account, with the ETF's distributions not counted (spec §12).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from app.market_data import UniverseRule
from app.strategies.base import Bars, Disposition, IndicatorStrategy, Judgement, Plot, Position

DEFAULTS: Mapping[str, Any] = {"warmup_sessions": 1}  # the day's own bar
ALWAYS_HOLD = "always_hold"


class TopixBuyAndHold(IndicatorStrategy):
    name = "topix_buy_and_hold_v1"
    plots: tuple[Plot, ...] = ()
    universe_rule = UniverseRule.TOPIX_ETF

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self.warmup_sessions = self.params["warmup_sessions"]
        if self.warmup_sessions < 1:
            raise ValueError(f"{self.name} 的预热期至少要 1 个开市日（当天的日线）")

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        return {}  # the rule reads nothing

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        if position is None:
            return Judgement(Disposition.HOLD, (ALWAYS_HOLD,), 1.0)
        return Judgement(Disposition.HOLD)
