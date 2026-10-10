"""Portfolio rules (spec §7.2): from a session's signals to the next open's
orders. Pure — no database — so the rules are tested on a few lines of
made-up data (spec A.4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from app.accounts.ledger import Position
from app.accounts.records import BUY, SELL, SKIPPED, Record
from app.market_data import UniverseRule
from app.strategies import Signal

LOT = 100


@dataclass(frozen=True)
class PortfolioRules:
    max_positions: int = 10
    max_weight: Decimal = Decimal("0.10")
    cash_floor: Decimal = Decimal("0.05")


def suggested_rules(universe_rule: UniverseRule) -> PortfolioRules:
    """The portfolio rules a new account starts from for a strategy buying
    under `universe_rule`; the user may change them. A universe of one ETF
    is held nearly whole — one position, up to all of the NAV, 5% kept as
    cash, so about 95% in 1306; stocks keep the defaults."""
    if universe_rule is UniverseRule.TOPIX_ETF:
        return PortfolioRules(max_positions=1, max_weight=Decimal(1), cash_floor=Decimal("0.05"))
    return PortfolioRules()


def plan_orders(
    *,
    day: date,
    execution_day: date,
    positions: Mapping[str, Position],
    exits: Sequence[Signal],
    candidates: Sequence[Signal],
    closes: Mapping[str, Decimal],
    cash: Decimal,
    nav: Decimal,
    rules: PortfolioRules,
    contenders: Sequence[Signal] = (),
) -> list[Record]:
    """`exits` are held codes told to sell (not those whose sell is already
    being placed again); `candidates` are codes in `day`'s universe, not
    held, that can be held. `contenders` are held codes, not in `exits`, that
    a strategy which ranks its holdings ranked that day: they and the
    candidates compete for the places the other holdings leave, and one
    ranked out is sold (`ranked_out`). `closes` are `day`'s execution closes."""
    def order(kind: str, signal: Signal, quantity: int, reason: dict | None = None, **outcome) -> Record:
        return Record(kind=kind, code=signal.code, signal_date=day, execution_date=execution_day,
                      planned_quantity=quantity, priority=signal.priority,
                      reason=reason or {"disposition": signal.disposition.value,
                                        "reason_codes": list(signal.reason_codes)},
                      **outcome)

    def best_first(signals: Sequence[Signal]) -> list[Signal]:
        return sorted(signals, key=lambda signal: (-(signal.priority or 0.0), signal.code))

    sells = [order(SELL, signal, positions[signal.code].quantity) for signal in exits]
    if contenders:
        unranked = len(positions) - len(sells) - len(contenders)  # holdings that keep their place
        places = max(rules.max_positions - unranked, 0)
        kept = {signal.code for signal in best_first([*contenders, *candidates])[:places]}
        sells += [order(SELL, signal, positions[signal.code].quantity,
                        {"disposition": "exit", "reason_codes": ["ranked_out"]})
                  for signal in sorted(contenders, key=lambda signal: signal.code) if signal.code not in kept]
        candidates = [signal for signal in candidates if signal.code in kept]
    free = rules.max_positions - (len(positions) - len(sells))
    ranked = best_first(candidates)[:max(free, 0)]
    target = nav * min(rules.max_weight, (1 - rules.cash_floor) / rules.max_positions)

    selling = sum((Decimal(sell.planned_quantity) * closes[sell.code] for sell in sells), Decimal(0))
    budget = cash + selling - rules.cash_floor * nav

    buys = []
    for signal in ranked:
        price = closes[signal.code]
        quantity = int((target / price / LOT).to_integral_value(rounding=ROUND_FLOOR)) * LOT
        if quantity == 0:
            buys.append(order(BUY, signal, 0, status=SKIPPED, outcome_reason="lot_unaffordable"))
        elif quantity * price > budget:
            buys.append(order(BUY, signal, quantity, status=SKIPPED, outcome_reason="insufficient_cash"))
        else:
            buys.append(order(BUY, signal, quantity))
            budget -= quantity * price
    return sells + buys
