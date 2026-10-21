"""`Recorded` (ticket 06a): the policy as a model experiment's replay sees
it. It notes what the strategy said each day and is the strategy in
everything else — whatever the strategy seam asks of a strategy, now or
later."""

from __future__ import annotations

from datetime import date

import pytest

from app.experiments.decisions import Recorded
from app.market_data import UniverseRule
from app.strategies import Disposition, Holding, Signal

DAY = date(2026, 3, 2)


class Told:
    name = "told_v1"
    warmup_sessions = 3
    plots = ()
    universe_rule = UniverseRule.PRIME_COMMON_STOCK
    reference_series = ("0000",)
    ranks_holdings = True
    a_later_field = "seam grew"  # the protocol may ask for more one day

    def evaluate(self, frame, day, holdings):
        return [Signal("A", Disposition.HOLD, ("model_rank",), {}, 0.5),
                Signal("B", Disposition.EXIT, ("score_missing",), {}, None),
                Signal("C", Disposition.STAY_OUT, ("score_missing",), {}, None)]


def test_recorded_is_its_strategy_in_everything_but_evaluate():
    recorded = Recorded(Told())

    assert (recorded.name, recorded.warmup_sessions, recorded.plots, recorded.universe_rule,
            recorded.reference_series, recorded.ranks_holdings, recorded.a_later_field) == (
        "told_v1", 3, (), UniverseRule.PRIME_COMMON_STOCK, ("0000",), True, "seam grew")
    with pytest.raises(AttributeError):
        recorded.not_there

    signals = recorded.evaluate(None, DAY, [Holding("B", 100, DAY)])

    assert [s.code for s in signals] == ["A", "B", "C"]
    assert recorded.held[DAY] == ["B"]
    assert recorded.said[DAY] == {"B": signals[1]}
    assert recorded.wanted[DAY] == ["A"]
