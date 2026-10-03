"""TOPIX momentum v1 (.scratch/topix-etf-strategies/spec.md, spec §6.5).

Its universe is 1306 alone, and its rule reads TOPIX alone — its reference
series. The past return is TOPIX's close over its close `lookback_sessions`
sessions earlier, less 1, counting back over the sessions TOPIX has a
close; it is worked out every session, but judged only on the check day,
the first session of each month:

- holding nothing, 1306 can be held while the past return is positive,
  ranked by it;
- holding 1306, it must be sold once the past return is negative;
- a past return of exactly 0 changes nothing, and neither does any other
  session: holding nothing it stays out (`not_check_day`), holding 1306 it
  keeps it.

The check day is a session whose previous date in the frame falls in an
earlier month — the frame's dates are the sessions, so a month that opens
on holidays has its check day on its first session. Without a TOPIX close
that day there is no signal, the next session is not a check day either,
and the account stays as it is until the next month's. An account started
in mid-month can buy no earlier than the next month's check day. How often
it judges is the rule itself, not a parameter: judging daily is another
version.

The past return is compared as TOPIX's close against the close it is
measured from, not as the ratio less 1 against 0, as the moving average's
thresholds are. No risk-free rate is taken off: Japan's short rates were
close to 0 over the sample. These are the strategy's own rules, not a
market regime: nothing of `topix_trend_vol_v1` is read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from app.market_data import TOPIX, UniverseRule
from app.strategies.base import Disposition, Judgement, Plot, ReferenceSeriesStrategy, whole_sessions

DEFAULTS: Mapping[str, Any] = {"lookback_sessions": 252, "warmup_sessions": 253}  # about 12 months, and the day's own
UP, FLAT, DOWN = "topix_momentum_up", "topix_momentum_flat", "topix_momentum_down"
NOT_CHECK_DAY = "not_check_day"


class TopixMomentum(ReferenceSeriesStrategy):
    name = "topix_momentum_v1"
    plots = (Plot("past_return", "separate"),)
    universe_rule = UniverseRule.TOPIX_ETF
    reference_series = (TOPIX,)

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self._lookback = whole_sessions(self.name, "回看长度", self.params["lookback_sessions"])
        self.warmup_sessions = self.params["warmup_sessions"]
        if self.warmup_sessions < self._lookback + 1:
            raise ValueError(f"{self.name} 的预热期 {self.warmup_sessions} 少于回看长度加当天"
                             f"（{self._lookback + 1} 个开市日）：过去收益还算不出来")

    def lines(self, closes: pd.DataFrame) -> dict[str, pd.Series]:
        topix = closes[TOPIX]
        lookback_close = topix.dropna().shift(self._lookback).reindex(topix.index)
        months = pd.Series([day.year * 12 + day.month for day in closes.index], index=closes.index)
        return {
            "topix_close": topix,
            "lookback_close": lookback_close,
            "past_return": topix / lookback_close - 1,
            "check_day": (months != months.shift()).astype(float),  # 1 on the first session of a month
        }

    def judge_on_reference(self, readings: dict[str, float], held: bool) -> Judgement:
        if not readings["check_day"]:
            return Judgement(Disposition.HOLD) if held else Judgement(Disposition.STAY_OUT, (NOT_CHECK_DAY,))
        close, then = readings["topix_close"], readings["lookback_close"]
        if held:
            return Judgement(Disposition.EXIT, (DOWN,)) if close < then else Judgement(Disposition.HOLD)
        if close > then:
            return Judgement(Disposition.HOLD, (UP,), readings["past_return"])
        return Judgement(Disposition.STAY_OUT, (DOWN,) if close < then else (FLAT,))
