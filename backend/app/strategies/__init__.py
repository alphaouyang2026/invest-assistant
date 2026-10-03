"""Strategies (spec §6, A.3): the stock strategies and the TOPIX ETF ones,
adapters behind one seam."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.market_data import UniverseRule
from app.strategies.base import (
    Disposition, Holding, Judgement, Plot, Signal, Strategy, WarmupFollows, codes_to_read,
)
from app.strategies import technical_rating, topix_buy_and_hold, topix_ma, topix_momentum, trend_pullback
from app.strategies.assembly import Candidate, SecurityHistory, entry_candidates, history

_STRATEGIES = {
    trend_pullback.TrendPullback.name: trend_pullback.TrendPullback,
    technical_rating.TechnicalRating.name: technical_rating.TechnicalRating,
    topix_buy_and_hold.TopixBuyAndHold.name: topix_buy_and_hold.TopixBuyAndHold,
    topix_ma.TopixMovingAverage.name: topix_ma.TopixMovingAverage,
    topix_momentum.TopixMomentum.name: topix_momentum.TopixMomentum,
}
STRATEGY_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    trend_pullback.TrendPullback.name: trend_pullback.DEFAULTS,
    technical_rating.TechnicalRating.name: technical_rating.DEFAULTS,
    topix_buy_and_hold.TopixBuyAndHold.name: topix_buy_and_hold.DEFAULTS,
    topix_ma.TopixMovingAverage.name: topix_ma.DEFAULTS,
    topix_momentum.TopixMomentum.name: topix_momentum.DEFAULTS,
}


@dataclass(frozen=True)
class StrategyInfo:
    """What a strategy declares of itself, without building it."""

    name: str
    defaults: Mapping[str, Any]
    universe_rule: UniverseRule
    warmup_follows: WarmupFollows | None


def strategy_infos() -> list[StrategyInfo]:
    return [StrategyInfo(name, STRATEGY_DEFAULTS[name], kind.universe_rule, kind.warmup_follows)
            for name, kind in _STRATEGIES.items()]


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
    "Strategy", "StrategyInfo", "WarmupFollows", "build_strategy", "codes_to_read", "entry_candidates", "history",
    "strategy_infos",
]
