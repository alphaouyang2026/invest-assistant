"""TOPIX ETF buy-and-hold v1, the control group (.scratch/topix-etf-strategies
spec): whatever can be judged can be held, and a holding is never sold.
Judged through `evaluate` on synthetic bars — no database."""

from __future__ import annotations

import pytest

from app.market_data import UniverseRule
from app.strategies import Disposition, Holding, build_strategy
from tests.frames import NO_BAR, frame_of, sessions

DAYS = sessions(30)
DAY = DAYS[-1]
ETF = "13060"  # 1306


def buy_and_hold(**params):
    return build_strategy("topix_buy_and_hold_v1", params)


def sliding(count: int) -> list[float]:
    """A long slide, which no other strategy would hold through."""
    return [3000.0 - 40 * n for n in range(count)]


def test_it_buys_1306_alone_and_draws_no_lines() -> None:
    strategy = buy_and_hold()

    assert strategy.universe_rule is UniverseRule.TOPIX_ETF
    assert (strategy.warmup_sessions, strategy.plots) == (1, ())


def test_holding_nothing_it_can_be_held_on_every_session_ranked_1() -> None:
    frame = frame_of({ETF: sliding(30)}, DAYS)
    strategy = buy_and_hold()

    for day in DAYS:
        [signal] = strategy.evaluate(frame, day, [])
        assert (signal.code, signal.disposition, signal.reason_codes, signal.priority) == (
            ETF, Disposition.HOLD, ("always_hold",), 1.0)


def test_a_holding_is_never_sold() -> None:
    frame = frame_of({ETF: sliding(30)}, DAYS)
    strategy = buy_and_hold()
    held = [Holding(ETF, 3100, DAYS[0])]

    for day in DAYS:
        [signal] = strategy.evaluate(frame, day, held)
        assert (signal.disposition, signal.reason_codes) == (Disposition.HOLD, ())


def test_no_signal_on_a_session_1306_is_halted_or_has_no_bar() -> None:
    """A holding stays as it is, and nothing is bought."""
    frame = frame_of({ETF: [*sliding(28), None, NO_BAR]}, DAYS)
    strategy = buy_and_hold()

    for day in DAYS[-2:]:
        assert strategy.evaluate(frame, day, []) == []
        assert strategy.evaluate(frame, day, [Holding(ETF, 3100, DAYS[0])]) == []


def test_the_warm_up_counts_the_days_own_bar() -> None:
    """By default a first bar can be judged at once; a longer warm-up waits
    for that many bars."""
    first_bar = frame_of({ETF: [3000.0]}, DAYS)
    four_bars = frame_of({ETF: sliding(4)}, DAYS)

    assert len(buy_and_hold().evaluate(first_bar, DAY, [])) == 1
    assert buy_and_hold(warmup_sessions=5).evaluate(four_bars, DAY, []) == []
    assert len(buy_and_hold(warmup_sessions=4).evaluate(four_bars, DAY, [])) == 1


def test_an_unknown_parameter_or_a_warm_up_under_one_session_is_refused() -> None:
    with pytest.raises(ValueError, match="ma_sessions"):
        buy_and_hold(ma_sessions=200)
    with pytest.raises(ValueError, match="预热期"):
        buy_and_hold(warmup_sessions=0)
