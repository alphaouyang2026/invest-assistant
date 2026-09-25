"""A session as an account sees it, and what happens at its open (spec
§7.1 steps 1–4, §7.3). Pure — no database."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from app.accounts.ledger import Ledger
from app.accounts.records import (
    BUY, DELISTING_SETTLEMENT, EXPIRED, FILLED, SELL, SKIPPED, SPLIT_ADJUSTMENT, Record,
)

LOT = 100


@dataclass(frozen=True)
class Bar:
    """One code's session in execution prices (spec §3.3)."""

    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    upper_limit_hit: bool = False
    lower_limit_hit: bool = False
    untradable: bool = False
    adjustment_factor: Decimal = Decimal(1)
    ex_rights_type: int | None = None


@dataclass(frozen=True)
class Session:
    day: date
    bars: Mapping[str, Bar]                                   # codes with a bar that day
    previous_closes: Mapping[str, Decimal] = field(default_factory=dict)  # the session before's execution closes
    delisted: frozenset[str] = frozenset()                    # codes no longer on the roster that day


@dataclass(frozen=True)
class Costs:
    commission_rate: Decimal = Decimal(0)
    commission_min: Decimal = Decimal(0)
    slippage: Decimal = Decimal("0.001")  # each side


SPLIT, REVERSE_SPLIT, RIGHTS_ISSUE = 1, 2, 3


def corporate_actions(ledger: Ledger, session: Session) -> tuple[list[Record], list[str]]:
    """Before the open (spec §7.1 steps 1–2). A split or reverse split on a
    held code divides its shares by the factor, a fraction of a share left
    by a reverse split paid out at the previous close × the factor; the
    day's orders for such a code follow — a sell takes the whole new
    holding, a buy is divided and rounded down to whole lots, or dropped.
    A rights issue changes nothing but is warned about. Returns the new
    event records and the orders changed, then the warnings."""
    day, records, warnings = session.day, [], []
    new_holding: dict[str, int] = {}
    for code, position in sorted(ledger.positions.items()):
        bar = session.bars.get(code)
        if bar is None or bar.adjustment_factor == 1:
            continue
        if bar.ex_rights_type == RIGHTS_ISSUE:
            warnings.append(f"{code} 在 {day.isoformat()} 配股：持仓未调整")
            continue
        exact = Decimal(position.quantity) / bar.adjustment_factor
        whole = int(exact.to_integral_value(rounding=ROUND_FLOOR))
        cashed = (exact - whole) * session.previous_closes[code] * bar.adjustment_factor
        new_holding[code] = whole
        records.append(Record(
            kind=SPLIT_ADJUSTMENT, code=code, signal_date=day, execution_date=day, status=FILLED,
            filled_quantity=whole - position.quantity, cash_delta=cashed,
            reason={"adjustment_factor": str(bar.adjustment_factor), "ex_rights_type": bar.ex_rights_type},
        ))

    for order in sorted(ledger.pending, key=lambda o: o.id or 0):
        bar = session.bars.get(order.code)
        if order.execution_date != day or bar is None or bar.ex_rights_type not in (SPLIT, REVERSE_SPLIT):
            continue
        if order.kind == SELL and order.code in new_holding:
            records.append(replace(order, planned_quantity=new_holding[order.code]))
        elif order.kind == BUY:
            lots = (Decimal(order.planned_quantity) / bar.adjustment_factor / LOT).to_integral_value(rounding=ROUND_FLOOR)
            quantity = int(lots) * LOT
            records.append(replace(order, planned_quantity=quantity) if quantity else
                           replace(order, planned_quantity=0, status=SKIPPED, outcome_reason="split_rounding"))

    for code in sorted(session.delisted & ledger.positions.keys()):
        position, last_close = ledger.positions[code], session.previous_closes[code]
        records.append(Record(
            kind=DELISTING_SETTLEMENT, code=code, signal_date=day, execution_date=day, status=FILLED,
            filled_quantity=position.quantity, fill_price=last_close, cash_delta=last_close * position.quantity,
        ))
    for order in sorted(ledger.pending, key=lambda o: o.id or 0):
        if order.code in session.delisted:
            records.append(replace(order, status=EXPIRED, outcome_reason="delisted"))
    return records, warnings


def open_session(orders: Sequence[Record], session: Session, *, cash: Decimal, costs: Costs) -> list[Record]:
    """The orders due at this open, carried out in turn: sells, then buys
    from the highest priority down (by code on a tie); what a sell brings
    in can pay for the buys after it. Returns them filled or expired, in
    the order carried out."""
    due = [order for order in orders if order.execution_date == session.day]
    sells = sorted((o for o in due if o.kind == SELL), key=lambda o: o.code)
    buys = sorted((o for o in due if o.kind == BUY), key=lambda o: (-(o.priority or 0.0), o.code))

    done = []
    for order in [*sells, *buys]:
        bar = session.bars.get(order.code)
        if bar is None or bar.untradable or bar.open is None:
            result = _expired(order, "untradable")
        elif order.kind == SELL:
            opened_on_limit = bar.lower_limit_hit and bar.open == bar.low
            result = _expired(order, "limit_down_open") if opened_on_limit else _sell(order, bar, costs)
        else:
            opened_on_limit = bar.upper_limit_hit and bar.open == bar.high
            result = _expired(order, "limit_up_open") if opened_on_limit else _buy(order, bar, cash, costs)
        cash += result.cash_delta
        done.append(result)
    return done


def replace_sells(results: Sequence[Record], *, day: date, execution_day: date) -> list[Record]:
    """Spec §7.1 step 4: each sell that expired at `day`'s open is placed
    again for the next — until it fills or the code is settled — without
    the strategy being asked again. Not after a delisting: nothing is left."""
    return [
        Record(kind=SELL, code=order.code, signal_date=day, execution_date=execution_day,
               planned_quantity=order.planned_quantity,
               reason={**order.reason, "replaces": order.id})
        for order in results
        if order.kind == SELL and order.status == EXPIRED and order.outcome_reason != "delisted"
    ]


def _expired(order: Record, why: str) -> Record:
    return replace(order, status=EXPIRED, outcome_reason=why)


def _sell(order: Record, bar: Bar, costs: Costs) -> Record:
    price = bar.open * (1 - costs.slippage)
    amount = price * order.planned_quantity
    fees = _fees(amount, costs)
    return replace(order, status=FILLED, filled_quantity=order.planned_quantity, fill_price=price, fees=fees,
                   cash_delta=amount - fees)


def _buy(order: Record, bar: Bar, cash: Decimal, costs: Costs) -> Record:
    """As many of the planned lots as the cash pays for, fees included;
    the cash floor is not checked here — only when orders are planned."""
    price = bar.open * (1 + costs.slippage)
    quantity = order.planned_quantity
    while quantity > 0 and price * quantity + _fees(price * quantity, costs) > cash:
        quantity -= LOT
    if quantity <= 0:
        return _expired(order, "insufficient_cash")
    amount = price * quantity
    fees = _fees(amount, costs)
    return replace(order, status=FILLED, filled_quantity=quantity, fill_price=price, fees=fees,
                   cash_delta=-(amount + fees))


def _fees(amount: Decimal, costs: Costs) -> Decimal:
    return max(costs.commission_min, amount * costs.commission_rate)
