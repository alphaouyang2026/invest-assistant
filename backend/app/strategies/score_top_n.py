"""Score top-N v1 (ticket 06a): holds the Prime stocks a model scores
highest, from a table of scores worked out elsewhere — out of fold, one per
stock on each decision day — and none of its own lines.

Its check days (判断日) are the table's decision days, which whoever made
the scores worked out from the trading calendar: the strategy counts no
sessions itself, because a paper account advancing a day at a time hands it
a frame that starts a warm-up before the day, not at the first decision
day. Every stock with a tradable bar that day gets a signal:

- a holding held `max_holding_sessions` sessions (when that is above 0), the
  day it was bought counting as the first, must be sold whatever the day
  (`time_exit`), as in short reversal;
- on any other session nothing changes: holding nothing it stays out,
  holding it it keeps it (`not_check_day`);
- on a decision day the model has nothing for — the table has no score
  that day, not one that is not NaN — nothing is opened and a holding keeps
  its place (`model_unavailable`): no score of an earlier day is used
  instead;
- on a decision day with scores, a stock with one can be held, held or not,
  ranked by it (`model_rank`); one without — it left the universe, a
  feature was missing — stays out, or is sold if held (`score_missing`).

Its holdings compete with the candidates (`ranks_holdings`): on a decision
day the portfolio rules keep the best `max_positions` of both in the day's
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

DEFAULTS: Mapping[str, Any] = {"max_holding_sessions": 0, "warmup_sessions": 1}
RANKED, NOT_CHECK_DAY, MODEL_UNAVAILABLE, SCORE_MISSING, TIME_EXIT = (
    "model_rank", "not_check_day", "model_unavailable", "score_missing", "time_exit")


@dataclass(frozen=True)
class ScoreTable:
    """Out-of-fold scores on the decision days. `decision_days` are worked
    out by whoever made the scores, from the trading calendar; `scores` is
    decision day → {code: score}, the higher the better, NaN no score. A
    decision day missing from `scores`, with no scores or only NaN, is one
    the model has nothing for (its fold failed to train, say). A day in
    `scores` that is not a decision day is refused: its scores would never
    be read."""

    decision_days: frozenset[date]
    scores: Mapping[date, Mapping[str, float]]

    def __post_init__(self) -> None:
        stray = sorted(set(self.scores) - set(self.decision_days))
        if stray:
            raise ValueError(f"分数表里有 {len(stray)} 天不是决策日："
                             + ", ".join(day.isoformat() for day in stray[:5]))


class ScoreTopN(IndicatorStrategy):
    name = "score_top_n_v1"
    plots: tuple[Plot, ...] = ()
    ranks_holdings = True

    def __init__(self, scores: ScoreTable, params: Mapping[str, Any]) -> None:
        unknown = sorted(set(params) - set(DEFAULTS))
        if unknown:
            raise ValueError(f"{self.name} 没有这些参数：{', '.join(unknown)}")
        super().__init__({**DEFAULTS, **params})
        holding = self.params["max_holding_sessions"]
        if not (isinstance(holding, int | float) and float(holding).is_integer() and holding >= 0):
            raise ValueError(f"{self.name} 的最长持有要是 0（不限）或至少 1 个开市日的整数，收到 {holding}")
        self._holding = int(holding)
        self.warmup_sessions = whole_sessions(self.name, "预热期", self.params["warmup_sessions"])
        self._decision_days = frozenset(scores.decision_days)
        self._scores = _usable(scores)

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        close = bars.close
        check_day = pd.Series([float(day in self._decision_days) for day in close.index], index=close.index)
        return {"score": self._score_line(close), "check_day": on_every_code(check_day, close)}

    def _score_line(self, like: pd.DataFrame) -> pd.DataFrame:
        """The table's score for each code on each session, NaN where it has
        none or the model has none that day."""
        table = pd.DataFrame.from_dict(self._scores, orient="index", dtype=float)
        return table.reindex(index=like.index, columns=like.columns)

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
    """The table's scores on the decision days the model has any: at least
    one score that is not NaN."""
    usable = {}
    for day, scored in table.scores.items():
        scores = {code: float(score) for code, score in scored.items()}
        if any(not math.isnan(score) for score in scores.values()):
            usable[day] = scores
    return usable


def _unchanged(holding: Holding | None, why: str) -> Judgement:
    """Nothing opened, a holding kept — not ranked, so it keeps its place."""
    return Judgement(Disposition.HOLD if holding else Disposition.STAY_OUT, (why,))
