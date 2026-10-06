"""Short reversal v1 (ticket 05 B, spec §6.6).

A Prime stock is judged every session on its own research closes. The past
return is the close over the close `return_sessions` sessions earlier, less
1, counting back over the sessions it has a bar:

- holding nothing, it can be held once its close is below the one it is
  measured from — it fell — ranked by how far it fell, the biggest fall
  first; a stock that is where it was or rose stays out;
- holding it, it must be sold once it has been held `max_holding_sessions`
  sessions, the day it was bought counting as the first (`time_exit`),
  whatever the price did since.

Which of the fallen are bought is the portfolio rules' doing: the candidates
in the day's universe, biggest fall first, fill the free places. So the
"weakest group" ticket 05 speaks of is the fallen stocks that rank within
the free places, not a fixed share of the universe — the strategy cannot
see the day's universe, the portfolio rules can.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from app.strategies.base import (
    Bars, Disposition, IndicatorStrategy, Judgement, Plot, Position, WarmupFollows, whole_sessions,
)

DEFAULTS: Mapping[str, Any] = {"return_sessions": 5, "max_holding_sessions": 5, "warmup_sessions": 6}
DROP, NO_DROP, TIME_EXIT = "short_term_drop", "no_short_term_drop", "time_exit"


class ShortReversal(IndicatorStrategy):
    name = "short_reversal_v1"
    plots = (Plot("past_return", "separate"),)
    warmup_follows = WarmupFollows("return_sessions", 1)  # the close that far back, and the day's own

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self._lookback = whole_sessions(self.name, "回看长度", self.params["return_sessions"])
        self._holding = whole_sessions(self.name, "最长持有", self.params["max_holding_sessions"])
        self.warmup_sessions = self.params["warmup_sessions"]
        needed = self._lookback + self.warmup_follows.extra
        if self.warmup_sessions < needed:
            raise ValueError(f"{self.name} 的预热期 {self.warmup_sessions} 少于回看长度加当天"
                             f"（{needed} 个开市日）：过去收益还算不出来")

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        close = bars.close
        lookback_close = bars.back(close, self._lookback)
        return {"close": close, "lookback_close": lookback_close, "past_return": close / lookback_close - 1}

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        if position:
            if position.sessions_held >= self._holding:
                return Judgement(Disposition.EXIT, (TIME_EXIT,))
            return Judgement(Disposition.HOLD)
        if readings["close"] < readings["lookback_close"]:
            return Judgement(Disposition.HOLD, (DROP,), -readings["past_return"])
        return Judgement(Disposition.STAY_OUT, (NO_DROP,))
