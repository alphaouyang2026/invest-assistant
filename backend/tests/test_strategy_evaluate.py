"""`Strategy.evaluate(frame, day, holdings)` (spec §6.2, A.3): the wiring
around the rules — who gets a signal, what a position's facts are, and
that nothing is seen from after `day`. The rules themselves are tested in
test_trend_pullback_rules.py and test_technical_rating_rules.py.
"""

from __future__ import annotations

import pytest

from app import indicators
from app.market_data import CLOSE, HIGH, LOW, MarketFrame
from app.strategies import Disposition, Holding, build_strategy
from tests.frames import NO_BAR, frame_of, sessions

DAYS = sessions(200)
DAY = DAYS[-1]


def zigzag(count: int) -> list[float]:
    """Nothing a strategy would act on: small swings around 100."""
    return [100.0 + (n % 7) for n in range(count)]


def test_a_code_gets_a_signal_once_it_has_the_warm_up_behind_it() -> None:
    strategy = build_strategy("trend_pullback_v1", {})
    frame = frame_of({"13010": zigzag(180), "13020": zigzag(179)}, DAYS)

    signals = strategy.evaluate(frame, DAY, [])

    assert strategy.warmup_sessions == 180
    assert [signal.code for signal in signals] == ["13010"]
    assert signals[0].disposition is Disposition.STAY_OUT


def rising(count: int) -> list[float]:
    """A steady uptrend: EMA20 above EMA60 and +DI above −DI throughout."""
    return [100.0 + 0.5 * n for n in range(count)]


# Only the exit under test can fire: no stop, no overbought fade.
ONLY_TIME_EXIT = {"atr_multiple": 1000, "rsi_overbought": 101}


def test_sessions_held_count_a_halted_bar_but_not_a_day_without_one() -> None:
    """Bought on DAYS[-4]; DAYS[-3] halted (an untradable bar); DAYS[-2] no
    bar at all; DAY: three sessions held."""
    base = rising(200)
    frame = frame_of({"13010": [*base[:197], None, NO_BAR, base[199]]}, DAYS)
    holding = [Holding("13010", 100, DAYS[-4])]

    def judged(max_sessions: int):
        strategy = build_strategy("trend_pullback_v1", ONLY_TIME_EXIT | {"max_holding_sessions": max_sessions})
        [signal] = strategy.evaluate(frame, DAY, holding)
        return signal.disposition, signal.reason_codes

    assert judged(3) == (Disposition.EXIT, ("time_exit",))
    assert judged(4) == (Disposition.HOLD, ())


def test_the_highest_close_is_counted_from_the_opening_session_only() -> None:
    """Up to a peak on DAYS[-7], then 0.3 lower each session. Bought on
    DAYS[-4], the highest close is that day's, 0.9 above DAY's; bought on
    the peak, it is 1.8 above. A stop 1.35 below the highest close tells
    the two apart."""
    closes = rising(194) + [rising(194)[-1] - 0.3 * n for n in range(1, 7)]
    frame = frame_of({"13010": closes}, DAYS)
    atr = indicators.atr(frame.wide(HIGH), frame.wide(LOW), frame.wide(CLOSE), 14)["13010"][DAY]
    strategy = build_strategy("trend_pullback_v1", {"atr_multiple": 1.35 / atr, "rsi_overbought": 101})

    [after_the_peak] = strategy.evaluate(frame, DAY, [Holding("13010", 100, DAYS[-4])])
    [on_the_peak] = strategy.evaluate(frame, DAY, [Holding("13010", 100, DAYS[-7])])

    assert after_the_peak.disposition is Disposition.HOLD
    assert (on_the_peak.disposition, on_the_peak.reason_codes) == (Disposition.EXIT, ("trailing_stop",))


def test_a_frame_starting_after_the_opening_session_is_refused() -> None:
    """The highest close since opening would come out too low and the stop
    would be wrong without a word, so it is an error instead."""
    frame = frame_of({"13010": rising(190)}, DAYS)
    strategy = build_strategy("trend_pullback_v1", {})

    with pytest.raises(ValueError, match="13010"):
        strategy.evaluate(frame, DAY, [Holding("13010", 100, DAYS[0])])


def test_a_holding_halted_that_day_gets_no_signal_and_stays_as_it_is() -> None:
    frame = frame_of({"13010": [*rising(199), None]}, DAYS)

    assert build_strategy("trend_pullback_v1", {}).evaluate(frame, DAY, [Holding("13010", 100, DAYS[-5])]) == []


def test_nothing_after_the_day_is_seen() -> None:
    """Judging day t from the whole frame equals judging it from the frame
    cut at t (spec §6.2)."""
    closes = {"13010": zigzag(200), "13020": rising(200), "13030": [*rising(150), *zigzag(50)]}
    whole = frame_of(closes, DAYS)
    day = DAYS[185]
    cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
    holdings = [Holding("13020", 100, DAYS[182])]

    for name in ("trend_pullback_v1",):
        strategy = build_strategy(name, {})
        assert strategy.evaluate(whole, day, holdings) == build_strategy(name, {}).evaluate(cut, day, holdings)


def test_the_indicators_are_worked_out_once_per_frame(monkeypatch) -> None:
    """Stepping through a backtest calls `evaluate` once a session on the
    same frame; the lines must not be worked out again each time."""
    calls = []
    real_rsi = indicators.rsi
    monkeypatch.setattr(indicators, "rsi", lambda *args: calls.append(1) or real_rsi(*args))
    frame = frame_of({"13010": zigzag(200)}, DAYS)
    strategy = build_strategy("trend_pullback_v1", {})

    for day in DAYS[-20:]:
        strategy.evaluate(frame, day, [])

    assert len(calls) == 1
