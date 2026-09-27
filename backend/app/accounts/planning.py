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
from app.strategies import Signal

LOT = 100


@dataclass(frozen=True)
class PortfolioRules:
    max_positions: int = 10
    max_weight: Decimal = Decimal("0.10")
    cash_floor: Decimal = Decimal("0.05")


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
) -> list[Record]:
    """`exits` are held codes told to sell (not those whose sell is already
    being placed again); `candidates` are codes in `day`'s universe, not
    held, that can be held. `closes` are `day`'s execution closes."""
    def order(kind: str, signal: Signal, quantity: int, **outcome) -> Record:
        return Record(kind=kind, code=signal.code, signal_date=day, execution_date=execution_day,
                      planned_quantity=quantity, priority=signal.priority,
                      reason={"disposition": signal.disposition.value, "reason_codes": list(signal.reason_codes)},
                      **outcome)

    sells = [order(SELL, signal, positions[signal.code].quantity) for signal in exits]
    free = rules.max_positions - (len(positions) - len(sells))
    ranked = sorted(candidates, key=lambda signal: (-(signal.priority or 0.0), signal.code))[:max(free, 0)]
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
