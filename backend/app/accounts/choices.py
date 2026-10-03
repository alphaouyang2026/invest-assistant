"""The strategies a new account can be opened with (spec §7.1): what each
declares of itself, paired with what the accounts make of it — the codes
its universe rule names and the portfolio rules suggested for it. The
strategy list API only translates this (spec A.6)."""

from __future__ import annotations

from dataclasses import dataclass

from app.accounts.planning import PortfolioRules, suggested_rules
from app.market_data import named_codes
from app.strategies import StrategyInfo, strategy_infos


@dataclass(frozen=True)
class StrategyChoice:
    strategy: StrategyInfo
    pool_codes: tuple[str, ...]  # the codes its universe rule names outright; none for a market segment
    suggested_rules: PortfolioRules


def strategy_choices() -> list[StrategyChoice]:
    return [StrategyChoice(info, named_codes(info.universe_rule), suggested_rules(info.universe_rule))
            for info in strategy_infos()]
