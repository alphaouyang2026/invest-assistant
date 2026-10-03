"""TOPIX moving average v1 (.scratch/topix-etf-strategies/spec.md, spec §6.5).

Its universe is 1306 alone, and its rule reads TOPIX alone — its reference
series — judged at each session's close:

- the average is the simple mean of TOPIX's last `ma_sessions` closes, the
  day's own included, counting back over the sessions TOPIX has a close;
- holding nothing, 1306 can be held once TOPIX closes more than `band`
  above its average, ranked by the deviation (close ÷ average − 1);
- holding 1306, it must be sold once TOPIX closes more than `band` below.

In between — a close exactly on either threshold included — nothing
changes. The thresholds are the average × (1 ± band), so a close of 101
against an average of 100 is on the 1% threshold, as it reads, rather
than a hair past it as the deviation worked out in floating point would
put it. With a band of 0 the rule is: above the average buy, below it sell.

These are the strategy's own rules, not a market regime: nothing of
`topix_trend_vol_v1` is read.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from app import indicators
from app.market_data import TOPIX, UniverseRule
from app.strategies.base import Disposition, Judgement, Plot, ReferenceSeriesStrategy, WarmupFollows, whole_sessions

DEFAULTS: Mapping[str, Any] = {"ma_sessions": 200, "band": 0.01, "warmup_sessions": 200}  # band: 0.01 is 1%
ABOVE, NEAR, BELOW = "topix_above_ma", "topix_near_ma", "topix_below_ma"


class TopixMovingAverage(ReferenceSeriesStrategy):
    name = "topix_ma_v1"
    plots = (Plot("topix_close", "separate"), Plot("topix_ma", "separate"))
    universe_rule = UniverseRule.TOPIX_ETF
    reference_series = (TOPIX,)
    warmup_follows = WarmupFollows("ma_sessions", 0)  # the average's closes, the day's own among them

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        window = whole_sessions(self.name, "均线窗口", self.params["ma_sessions"])
        band = self.params["band"]
        self.warmup_sessions = self.params["warmup_sessions"]
        if not (isinstance(band, int | float) and math.isfinite(band) and band >= 0):
            raise ValueError(f"{self.name} 的缓冲带要是不小于 0 的比例（0.01 表示 1%），收到 {band}")
        if self.warmup_sessions < window + self.warmup_follows.extra:
            raise ValueError(f"{self.name} 的预热期 {self.warmup_sessions} 比均线窗口 {window} 短：均线还算不出来")
        self._window = window

    def lines(self, closes: pd.DataFrame) -> dict[str, pd.Series]:
        topix = closes[TOPIX]
        average = indicators.sma(topix, self._window)
        return {"topix_close": topix, "topix_ma": average, "deviation": topix / average - 1}

    def judge_on_reference(self, readings: dict[str, float], held: bool) -> Judgement:
        close, average, band = readings["topix_close"], readings["topix_ma"], self.params["band"]
        below = close < average * (1 - band)
        if held:
            return Judgement(Disposition.EXIT, (BELOW,)) if below else Judgement(Disposition.HOLD)
        if close > average * (1 + band):
            return Judgement(Disposition.HOLD, (ABOVE,), readings["deviation"])
        return Judgement(Disposition.STAY_OUT, (BELOW,) if below else (NEAR,))
