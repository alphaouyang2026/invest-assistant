"""What a model experiment's replay decided, day by day (ticket 06a).

`Recorded` wraps the policy as `replay_day` sees it and notes, each day,
what it said of every code held that morning and which others it would
hold — `replay_day` itself is not touched. `day_records` then lays each
replayed day out from those notes and the replay's own days
(`Replay.days`, the accounts module's reading of its ledger): the
holdings' dispositions and reasons, the orders planned at the close (with
what became of them), what filled or expired at the open, the holdings the
plan aims at and those actually held at the close, the cash, the NAV, and
which portfolio constraints bit.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.accounts.accounts import Prices
from app.accounts.records import BUY, SELL, Record
from app.accounts.replay import Replay
from app.accounts.replay_metrics import holding_lines
from app.market_data import MarketFrame
from app.strategies import Disposition, Holding, Signal, Strategy


class Recorded:
    """`strategy` as the replay sees it, noting what it said each day.
    Everything but `evaluate` is the strategy's own, whatever the strategy
    seam asks of it."""

    def __init__(self, strategy: Strategy) -> None:
        self.strategy = strategy
        self.held: dict[date, list[str]] = {}              # the codes held that morning
        self.said: dict[date, dict[str, Signal]] = {}      # its signals for them
        self.wanted: dict[date, list[str]] = {}            # codes not held it would hold

    def __getattr__(self, name: str) -> Any:
        strategy = vars(self).get("strategy")
        if strategy is None:
            raise AttributeError(name)
        return getattr(strategy, name)

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]:
        signals = self.strategy.evaluate(frame, day, holdings)
        held = {holding.code for holding in holdings}
        self.held[day] = sorted(held)
        self.said[day] = {s.code: s for s in signals if s.code in held}
        self.wanted[day] = [s.code for s in signals if s.disposition is Disposition.HOLD and s.code not in held]
        return signals


def day_records(replay: Replay, recorded: Recorded, prices: Prices, universes: Mapping[date, Sequence[str]],
                decision_days: Sequence[date], scored: Mapping[date, Mapping[str, Any]]) -> list[dict]:
    """One JSON-ready record per replayed day, oldest first. `scored` holds
    the kept scores by decision day (see `report.kept_scores`)."""
    deciding = set(decision_days)
    out = []
    for replayed in replay.days():
        day, positions = replayed.day, replayed.positions
        closes = prices.closes(day, positions)
        pool = set(universes.get(day, []))
        wanted = [code for code in recorded.wanted.get(day, []) if code in pool]
        buys = [o for o in replayed.planned if o.kind == BUY]
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
            "orders": [_order(o) for o in replayed.planned],
            "executions": [_execution(r) for r in replayed.opened],
            "target": [{"code": code, "quantity": quantity} for code, quantity in sorted(replayed.target().items())],
            "holdings": holding_lines(sorted(positions.values(), key=lambda p: p.code), closes),
            "cash": float(replayed.cash),
            "nav": float(replayed.point.nav),
            "constraints": {
                "skipped": dict(sorted(Counter(o.outcome_reason for o in replayed.given_up()).items())),
                "adv20_capped": sum(o.reason.get("capped") == "adv20" for o in buys),
                "ranked_out": sum("ranked_out" in o.reason.get("reason_codes", ()) and "replaces" not in o.reason
                                  for o in replayed.planned if o.kind == SELL),
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
