"""Score top-N v1 (ticket 06a): holds the Prime stocks a model scores
highest, from a table of scores worked out elsewhere — out of fold, one per
stock on each decision day — and none of its own lines.

Its check days (判断日) are counted on the frame's sessions: the session on
or after `anchor` that is a whole number of `rebalance_sessions` sessions
from the first such session. Every stock with a tradable bar that day gets a
signal:

- a holding held `max_holding_sessions` sessions (when that is above 0), the
  day it was bought counting as the first, must be sold whatever the day
  (`time_exit`), as in short reversal;
- on any other session nothing changes: holding nothing it stays out,
  holding it it keeps it (`not_check_day`);
- on a check day the model has nothing for — the day is in the table's
  `unavailable`, or the table has no score that day, not one — nothing is
  opened and a holding keeps its place (`model_unavailable`): no score of
  an earlier day is used instead;
- on a check day with scores, a stock with one can be held, held or not,
  ranked by it (`model_rank`); one without — it left the universe, a
  feature was missing — stays out, or is sold if held (`score_missing`).

Its holdings compete with the candidates (`ranks_holdings`): on a check day
the portfolio rules keep the best `max_positions` of both in the day's
universe and sell a holding ranked out (spec §7.2). A score is only an
order: it is never read as a return to clear.

Not one of the strategies a new account can pick (`build_strategy`): it is
built round a table of scores, by whoever worked them out.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from app.market_data import MarketFrame
from app.strategies.base import (
    Bars, Disposition, Holding, IndicatorStrategy, Judgement, Plot, on_every_code, whole_sessions,
)

DEFAULTS: Mapping[str, Any] = {"rebalance_sessions": 5, "max_holding_sessions": 0, "warmup_sessions": 1}
RANKED, NOT_CHECK_DAY, MODEL_UNAVAILABLE, SCORE_MISSING, TIME_EXIT = (
    "model_rank", "not_check_day", "model_unavailable", "score_missing", "time_exit")


@dataclass(frozen=True)
class ScoreTable:
    """Out-of-fold scores: decision day → {code: score}, the higher the
    better; NaN is no score. `unavailable` are the decision days the model
    has nothing for (its fold failed to train, say); a day there counts as
    one without scores, whatever `scores` holds for it."""

    scores: Mapping[date, Mapping[str, float]]
    unavailable: frozenset[date] = frozenset()


class ScoreTopN(IndicatorStrategy):
    name = "score_top_n_v1"
    plots: tuple[Plot, ...] = ()
    ranks_holdings = True

    def __init__(self, scores: ScoreTable, params: Mapping[str, Any]) -> None:
        unknown = sorted(set(params) - {"anchor", *DEFAULTS})
        if unknown:
            raise ValueError(f"{self.name} 没有这些参数：{', '.join(unknown)}")
        super().__init__({**DEFAULTS, **params})
        if "anchor" not in self.params:
            raise ValueError(f"{self.name} 要有锚点 anchor：第一个判断日，ISO 日期")
        try:
            self._anchor = date.fromisoformat(str(self.params["anchor"]))
        except ValueError:
            raise ValueError(f"{self.name} 的锚点要是 ISO 日期（如 2025-01-06），收到 {self.params['anchor']!r}") from None
        self._every = whole_sessions(self.name, "调仓间隔", self.params["rebalance_sessions"])
        holding = self.params["max_holding_sessions"]
        if not (isinstance(holding, int | float) and float(holding).is_integer() and holding >= 0):
            raise ValueError(f"{self.name} 的最长持有要是 0（不限）或至少 1 个开市日的整数，收到 {holding}")
        self._holding = int(holding)
        self.warmup_sessions = whole_sessions(self.name, "预热期", self.params["warmup_sessions"])
        self._scores = _usable(scores)

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        close = bars.close
        return {"score": self._score_line(close), "check_day": on_every_code(self._check_days(close.index), close)}

    def _score_line(self, like: pd.DataFrame) -> pd.DataFrame:
        """The table's score for each code on each session, NaN where it has
        none or the model has none that day."""
        table = pd.DataFrame.from_dict(self._scores, orient="index", dtype=float)
        return table.reindex(index=like.index, columns=like.columns)

    def _check_days(self, index: pd.Index) -> pd.Series:
        """1 on the sessions of `index` on or after the anchor a whole number
        of `rebalance_sessions` from the first of them, 0 on the others. A
        frame that starts after the anchor cannot tell which those are."""
        if len(index) and index[0] > self._anchor:
            raise ValueError(f"{self.name} 的行情从 {index[0]} 才开始，晚于锚点 {self._anchor}：数不出哪天是判断日")
        since = pd.Series([day >= self._anchor for day in index], index=index)
        counted = since.cumsum() - 1  # sessions after the first on or after the anchor
        return (since & (counted % self._every == 0)).astype(float)

    def _judge_code(self, frame: MarketFrame, day: date, readings: dict[str, float],
                    holding: Holding | None) -> Judgement:
        """Overridden rather than `judge`: whether the model has scores is
        the day's, not a reading of the code's."""
        if holding and self._holding and self._position(frame, holding, day).sessions_held >= self._holding:
            return Judgement(Disposition.EXIT, (TIME_EXIT,))
        if not readings["check_day"]:
            return _unchanged(holding, NOT_CHECK_DAY)
        if day not in self._scores:
            return _unchanged(holding, MODEL_UNAVAILABLE)
        if math.isnan(readings["score"]):
            return Judgement(Disposition.EXIT if holding else Disposition.STAY_OUT, (SCORE_MISSING,))
        return Judgement(Disposition.HOLD, (RANKED,), readings["score"])


def _usable(table: ScoreTable) -> dict[date, dict[str, float]]:
    """The table's scores on the days the model has any: not unavailable,
    and at least one score that is not NaN."""
    usable = {}
    for day, scored in table.scores.items():
        scores = {code: float(score) for code, score in scored.items()}
        if day not in table.unavailable and any(not math.isnan(score) for score in scores.values()):
            usable[day] = scores
    return usable


def _unchanged(holding: Holding | None, why: str) -> Judgement:
    """Nothing opened, a holding kept — not ranked, so it keeps its place."""
    return Judgement(Disposition.HOLD if holding else Disposition.STAY_OUT, (why,))
