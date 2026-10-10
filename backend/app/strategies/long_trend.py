"""Long trend v1 (ticket 05 A, spec §6.6).

A Prime stock is judged on its own research closes against their simple
moving average over `sma_sessions` bars, counting back over the sessions it
has a bar — only on the check day, the first session of each month:

- holding nothing, it can be held while the close is above the average,
  ranked by how far above (the close over the average, less 1);
- holding it, it must be sold once the close is not above the average —
  exactly on it is not above;
- on any other session nothing changes: holding nothing it stays out
  (`not_check_day`), holding it it keeps it.

How often it judges is the rule itself, not a parameter, as with TOPIX
momentum. A stock without a tradable bar on the check day has no signal that
month. Holdings are not ranked against the candidates: one stays while it is
above its average however many others rank higher.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from app import indicators
from app.strategies.base import (
    Bars, Disposition, IndicatorStrategy, Judgement, Plot, Position, WarmupFollows, check_days, on_every_code,
    whole_sessions,
)

DEFAULTS: Mapping[str, Any] = {"sma_sessions": 200, "warmup_sessions": 200}
ABOVE, NOT_ABOVE = "above_sma", "not_above_sma"
NOT_CHECK_DAY = "not_check_day"


class LongTrend(IndicatorStrategy):
    name = "long_trend_v1"
    plots = (Plot("sma", "price"),)
    warmup_follows = WarmupFollows("sma_sessions", 0)  # the average's closes, the day's own among them

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self._window = whole_sessions(self.name, "均线窗口", self.params["sma_sessions"])
        self.warmup_sessions = self.params["warmup_sessions"]
        if self.warmup_sessions < self._window:
            raise ValueError(f"{self.name} 的预热期 {self.warmup_sessions} 少于均线窗口 {self._window}：均线还算不出来")

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        close = bars.close
        sma = indicators.sma(close, self._window)
        return {"close": close, "sma": sma, "deviation": close / sma - 1,
                "check_day": on_every_code(check_days(close.index), close)}

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        if not readings["check_day"]:
            return Judgement(Disposition.HOLD) if position else Judgement(Disposition.STAY_OUT, (NOT_CHECK_DAY,))
        above = readings["close"] > readings["sma"]
        if position:
            return Judgement(Disposition.HOLD) if above else Judgement(Disposition.EXIT, (NOT_ABOVE,))
        if above:
            return Judgement(Disposition.HOLD, (ABOVE,), readings["deviation"])
        return Judgement(Disposition.STAY_OUT, (NOT_ABOVE,))
