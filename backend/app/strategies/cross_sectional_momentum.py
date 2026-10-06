"""Cross-sectional momentum v1 (ticket 05 C, spec §6.6).

A Prime stock's momentum is its research close `skip_sessions` sessions back
over its close `momentum_sessions` sessions back, less 1, counting back over
the sessions it has a bar: the return over the window with its last few
sessions left out, because a stock's last month tends to turn back (ticket
05 B). The defaults, 126 and 21, are "6-1": six months less the last one.
It is worked out every session, but judged only on the check day, the first
session of each month:

- every stock it can judge that day can be held, held or not, ranked by its
  momentum — the ranking is across stocks, so a fall can rank too;
- on any other session nothing changes: holding nothing it stays out
  (`not_check_day`), holding it it keeps it.

Its holdings compete with the candidates (`ranks_holdings`): on the check
day the portfolio rules keep the best `max_positions` of both in the day's
universe and sell a holding ranked out (spec §7.2) — swaps only, a holding
kept is not resized.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from app.strategies.base import (
    Bars, Disposition, IndicatorStrategy, Judgement, Plot, Position, WarmupFollows, check_days, on_every_code,
    whole_sessions,
)

DEFAULTS: Mapping[str, Any] = {"momentum_sessions": 126, "skip_sessions": 21, "warmup_sessions": 127}
RANKED, NOT_CHECK_DAY = "momentum_rank", "not_check_day"


class CrossSectionalMomentum(IndicatorStrategy):
    name = "cross_sectional_momentum_v1"
    plots = (Plot("momentum", "separate"),)
    warmup_follows = WarmupFollows("momentum_sessions", 1)  # the close that far back, and the day's own
    ranks_holdings = True

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self._window = whole_sessions(self.name, "回看长度", self.params["momentum_sessions"])
        skip = self.params["skip_sessions"]
        if not (isinstance(skip, int | float) and float(skip).is_integer() and 0 <= skip < self._window):
            raise ValueError(f"{self.name} 跳过的开市日数要是 0 到回看长度 {self._window} 之间（不含）的整数，收到 {skip}")
        self._skip = int(skip)
        self.warmup_sessions = self.params["warmup_sessions"]
        needed = self._window + self.warmup_follows.extra
        if self.warmup_sessions < needed:
            raise ValueError(f"{self.name} 的预热期 {self.warmup_sessions} 少于回看长度加当天"
                             f"（{needed} 个开市日）：动量还算不出来")

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        close = bars.close
        from_close = bars.back(close, self._window)
        to_close = bars.back(close, self._skip) if self._skip else close
        return {"close": close, "from_close": from_close, "to_close": to_close, "momentum": to_close / from_close - 1,
                "check_day": on_every_code(check_days(close.index), close)}

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        if readings["check_day"]:
            return Judgement(Disposition.HOLD, (RANKED,), readings["momentum"])
        return Judgement(Disposition.HOLD) if position else Judgement(Disposition.STAY_OUT, (NOT_CHECK_DAY,))
