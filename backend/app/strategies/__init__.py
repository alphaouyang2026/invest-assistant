"""Strategies (spec §6, A.3): two adapters behind one seam."""

from collections.abc import Mapping
from typing import Any

from app.strategies.base import Disposition, Holding, Judgement, Plot, Signal, Strategy
from app.strategies import technical_rating, trend_pullback
from app.strategies.assembly import Candidate, SecurityHistory, entry_candidates, history

_STRATEGIES = {
    trend_pullback.TrendPullback.name: trend_pullback.TrendPullback,
    technical_rating.TechnicalRating.name: technical_rating.TechnicalRating,
}
STRATEGY_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    trend_pullback.TrendPullback.name: trend_pullback.DEFAULTS,
    technical_rating.TechnicalRating.name: technical_rating.DEFAULTS,
}


def build_strategy(name: str, params: Mapping[str, Any]) -> Strategy:
    """`params` override the defaults; anything left out keeps its default.
    A name the strategy does not have is refused rather than ignored."""
    if name not in _STRATEGIES:
        raise ValueError(f"没有这个策略：{name}")
    unknown = sorted(set(params) - set(STRATEGY_DEFAULTS[name]))
    if unknown:
        raise ValueError(f"{name} 没有这些参数：{', '.join(unknown)}")
    return _STRATEGIES[name](params)


__all__ = [
    "STRATEGY_DEFAULTS", "Candidate", "Disposition", "Holding", "Judgement", "Plot", "SecurityHistory", "Signal",
    "Strategy", "build_strategy", "entry_candidates", "history",
]
