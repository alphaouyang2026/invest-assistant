"""What a model experiment's replay decided, day by day (ticket 06a).

`Recorded` wraps the policy as `replay_day` sees it and notes, each day,
what it said of every code held that morning and which others it would
hold — `replay_day` itself is not touched. `day_records` then lays each
replayed day out from those notes and the replay's own ledger and NAV: the
holdings' dispositions and reasons, the orders planned at the close (with
what became of them), what filled or expired at the open, the holdings the
plan aims at and those actually held at the close, the cash, the NAV, and
which portfolio constraints bit.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.accounts.accounts import Prices
from app.accounts.records import BUY, EXPIRED, FILLED, SELL, SKIPPED, Record
from app.accounts.replay import Replay
from app.market_data import MarketFrame
from app.strategies import Disposition, Holding, Signal, Strategy


class Recorded:
    """`strategy` as the replay sees it, noting what it said each day."""

    def __init__(self, strategy: Strategy) -> None:
        self.strategy = strategy
        self.name, self.warmup_sessions, self.plots = strategy.name, strategy.warmup_sessions, strategy.plots
        self.universe_rule, self.reference_series = strategy.universe_rule, strategy.reference_series
        self.ranks_holdings = strategy.ranks_holdings
        self.held: dict[date, list[str]] = {}              # the codes held that morning
        self.said: dict[date, dict[str, Signal]] = {}      # its signals for them
        self.wanted: dict[date, list[str]] = {}            # codes not held it would hold

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]:
        signals = self.strategy.evaluate(frame, day, holdings)
        held = {holding.code for holding in holdings}
        self.held[day] = sorted(held)
        self.said[day] = {s.code: s for s in signals if s.code in held}
        self.wanted[day] = [s.code for s in signals if s.disposition is Disposition.HOLD and s.code not in held]
        return signals


def day_records(replay: Replay, recorded: Recorded, prices: Prices, universes: Mapping[date, Sequence[str]],
                days: Sequence[date], decision_days: Sequence[date],
                scored: Mapping[date, Mapping[str, Any]]) -> list[dict]:
    """One JSON-ready record per replayed day, oldest first. `scored` holds
    the kept scores by decision day (see `report.kept_scores`)."""
    planned: dict[date, list[Record]] = defaultdict(list)
    executed: dict[date, list[Record]] = defaultdict(list)
    for record in replay.ledger.records:
        if record.kind in (BUY, SELL):
            planned[record.signal_date].append(record)
            if record.status in (FILLED, EXPIRED) or record.outcome_reason == "split_rounding":
                executed[record.execution_date].append(record)
        else:  # a split adjustment or a delisting settlement, on its day
            executed[record.execution_date].append(record)
    deciding = set(decision_days)
    out = []
    for (day, cash, positions), point in zip(replay.ledger.by_session(days), replay.points, strict=True):
        closes = prices.closes(day, positions)
        orders = planned[day]
        # Those the portfolio rules gave up on at the close were never placed for the next open.
        given_up = [o for o in orders if o.status == SKIPPED and o.outcome_reason != "split_rounding"]
        live = [o for o in orders if not (o.status == SKIPPED and o.outcome_reason != "split_rounding")]
        target = {code: p.quantity for code, p in positions.items()}
        for order in live:
            if order.kind == SELL:
                target.pop(order.code, None)
            else:
                target[order.code] = target.get(order.code, 0) + order.planned_quantity
        pool = set(universes.get(day, []))
        wanted = [code for code in recorded.wanted.get(day, []) if code in pool]
        buys = [o for o in orders if o.kind == BUY]
        entry = scored.get(day) if day in deciding else None
        out.append({
            "date": day.isoformat(),
            "decision_day": day in deciding,
            "model_available": None if day not in deciding else entry is not None,
            "fold": entry["fold"] if entry else None,
            "universe": len(pool),
            "scored": len(entry["scores"]) if entry else 0,
            "holdings_decisions": [_decision(code, recorded.said.get(day, {}).get(code))
                                   for code in recorded.held.get(day, [])],
            "candidates": len(wanted),
            "orders": [_order(o) for o in orders],
            "executions": [_execution(r) for r in executed[day]],
            "target": [{"code": code, "quantity": quantity} for code, quantity in sorted(target.items())],
            "holdings": [{"code": p.code, "quantity": p.quantity, "opened_on": p.opened_on.isoformat(),
                          "cost": float(p.cost), "close": float(closes[p.code]),
                          "value": float(p.quantity * closes[p.code])}
                         for p in sorted(positions.values(), key=lambda p: p.code)],
            "cash": float(cash),
            "nav": float(point.nav),
            "constraints": {
                "skipped": dict(sorted(Counter(o.outcome_reason for o in given_up).items())),
                "adv20_capped": sum(o.reason.get("capped") == "adv20" for o in buys),
                "ranked_out": sum("ranked_out" in o.reason.get("reason_codes", ()) and "replaces" not in o.reason
                                  for o in orders if o.kind == SELL),
                "unplaced_candidates": max(len(wanted) - len(buys), 0),
            },
        })
    return out


def _decision(code: str, signal: Signal | None) -> dict:
    """A holding's signal that morning — none without a tradable bar."""
    if signal is None:
        return {"code": code, "disposition": None, "reason_codes": ["no_signal"], "score": None}
    score = signal.indicators.get("score")
    return {"code": code, "disposition": signal.disposition.value, "reason_codes": list(signal.reason_codes),
            "score": None if score is None or math.isnan(score) else score}


def _order(record: Record) -> dict:
    return {"sequence": record.id, "kind": record.kind, "code": record.code,
            "execution_date": record.execution_date.isoformat(), "planned_quantity": record.planned_quantity,
            "priority": record.priority, "reason_codes": list(record.reason.get("reason_codes", [])),
            "capped": record.reason.get("capped"), "replaces": record.reason.get("replaces"),
            "status": record.status, "outcome_reason": record.outcome_reason}


def _execution(record: Record) -> dict:
    return {"sequence": record.id, "kind": record.kind, "code": record.code,
            "signal_date": record.signal_date.isoformat(), "status": record.status,
            "outcome_reason": record.outcome_reason, "filled_quantity": record.filled_quantity,
            "fill_price": None if record.fill_price is None else float(record.fill_price),
            "fees": float(record.fees), "cash_delta": float(record.cash_delta)}
