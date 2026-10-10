"""Short reversal v1 (ticket 05 B, spec §6.6): every session, a Prime stock
whose close fell over the last few sessions can be held, the biggest fall
first, and a holding is sold once it has been held its fixed number of
sessions. Judged through `evaluate` on synthetic bars — no database."""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.market_data import MarketFrame, UniverseRule
from app.strategies import STRATEGY_DEFAULTS, Disposition, Holding, Plot, WarmupFollows, build_strategy
from tests.frames import NO_BAR, frame_of, sessions, weekdays_through

HOLD, EXIT, STAY_OUT = Disposition.HOLD, Disposition.EXIT, Disposition.STAY_OUT
DROP, NO_DROP, TIME_EXIT = ("short_term_drop",), ("no_short_term_drop",), ("time_exit",)

DAY = date(2025, 10, 15)  # a Wednesday


def reversal(**params):
    return build_strategy("short_reversal_v1", params)


def test_it_buys_prime_stocks_on_their_own_bars_and_draws_the_past_return_in_a_pane_of_its_own() -> None:
    strategy = reversal()

    assert STRATEGY_DEFAULTS["short_reversal_v1"] == {
        "return_sessions": 5, "max_holding_sessions": 5, "warmup_sessions": 6}
    assert (strategy.universe_rule, strategy.reference_series) == (UniverseRule.PRIME_COMMON_STOCK, ())
    assert strategy.warmup_sessions == 6
    assert strategy.warmup_follows == WarmupFollows("return_sessions", 1)
    assert strategy.plots == (Plot("past_return", "separate"),)
    assert strategy.ranks_holdings is False


def test_holding_nothing_a_stock_that_fell_can_be_held_the_biggest_fall_first() -> None:
    """Two sessions back: A fell 10%, B 2%, C is where it was, D rose."""
    days = weekdays_through(DAY, 3)
    frame = frame_of({"A": [100.0, 95.0, 90.0], "B": [50.0, 52.0, 49.0], "C": [80.0, 70.0, 80.0],
                      "D": [10.0, 10.0, 11.0]}, days)

    signals = reversal(return_sessions=2, warmup_sessions=3).evaluate(frame, DAY, [])

    assert [(s.code, s.disposition, s.reason_codes) for s in signals] == [
        ("A", HOLD, DROP), ("B", HOLD, DROP), ("C", STAY_OUT, NO_DROP), ("D", STAY_OUT, NO_DROP)]
    a, b = signals[:2]
    assert a.priority == pytest.approx(0.10) and b.priority == pytest.approx(0.02)
    assert a.indicators == {"close": 90.0, "lookback_close": 100.0, "past_return": pytest.approx(-0.10)}


def test_holding_it_it_is_sold_once_held_for_the_holding_sessions_whatever_the_price_did() -> None:
    """Bought on the third of six sessions: on the last it has been held for
    four, counting the day it was bought as the first."""
    days = weekdays_through(DAY, 6)
    frame = frame_of({"A": [100.0, 99.0, 98.0, 97.0, 120.0, 90.0]}, days)
    holding = [Holding("A", 100, days[2])]

    def judged(**params) -> tuple:
        [signal] = reversal(return_sessions=2, warmup_sessions=3, **params).evaluate(frame, DAY, holding)
        return signal.disposition, signal.reason_codes

    assert judged(max_holding_sessions=4) == (EXIT, TIME_EXIT)
    assert judged(max_holding_sessions=3) == (EXIT, TIME_EXIT)
    assert judged(max_holding_sessions=5) == (HOLD, ())


def test_the_past_return_counts_back_over_the_sessions_the_stock_has_a_bar() -> None:
    days = weekdays_through(DAY, 5)
    frame = frame_of({"A": [90.0, 100.0, NO_BAR, 103.0, 95.0]}, days)

    [signal] = reversal(return_sessions=2, warmup_sessions=3).evaluate(frame, DAY, [])

    assert signal.indicators["lookback_close"] == 100.0


def test_no_signal_until_the_stock_has_the_return_sessions_and_the_day_s_own_close_or_on_a_halt() -> None:
    days = weekdays_through(DAY, 6)
    frame = frame_of({"short": [100.0] * 5, "enough": [100.0] * 6, "halted": [100.0] * 5 + [None]}, days)

    assert [s.code for s in reversal().evaluate(frame, DAY, [])] == ["enough"]
    assert reversal(warmup_sessions=7).evaluate(frame, DAY, []) == []


def test_nothing_after_the_day_is_seen() -> None:
    days = sessions(80, start=date(2025, 1, 6))
    whole = frame_of({"A": [100 + 10 * math.sin(n / 3) for n in range(80)],
                      "B": [100 + 10 * math.cos(n / 2) for n in range(80)]}, days)
    seen = set()

    for day in days[10:]:
        cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
        for holdings in ([], [Holding("A", 100, days[5]), Holding("B", 100, days[8])]):
            judged_whole = reversal().evaluate(whole, day, holdings)
            assert judged_whole == reversal().evaluate(cut, day, holdings)
            seen.update((signal.disposition, signal.reason_codes) for signal in judged_whole)

    assert seen == {(HOLD, DROP), (STAY_OUT, NO_DROP), (EXIT, TIME_EXIT), (HOLD, ())}


def test_an_unknown_parameter_a_warm_up_short_of_the_return_or_a_window_that_cannot_be_is_refused() -> None:
    with pytest.raises(ValueError, match="sma_sessions"):
        reversal(sma_sessions=5)
    with pytest.raises(ValueError, match="预热期"):
        reversal(warmup_sessions=5)
    with pytest.raises(ValueError, match="预热期"):
        reversal(return_sessions=20)  # the warm-up left at 6
    with pytest.raises(ValueError, match="回看长度"):
        reversal(return_sessions=0, warmup_sessions=1)
    with pytest.raises(ValueError, match="最长持有"):
        reversal(max_holding_sessions=0)
    with pytest.raises(ValueError, match="最长持有"):
        reversal(max_holding_sessions=2.5)
    assert reversal(return_sessions=20, max_holding_sessions=10, warmup_sessions=21).warmup_sessions == 21
