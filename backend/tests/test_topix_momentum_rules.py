"""TOPIX momentum v1 (.scratch/topix-etf-strategies spec, ticket 03): on
the first session of each month — its check day — 1306 is bought while
TOPIX's past return is positive and sold once it is negative; on every
other session nothing changes. Judged through `evaluate` on synthetic bars
with TOPIX, the reference series, beside the ETF — no database."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.market_data import TOPIX, MarketFrame, UniverseRule
from app.strategies import STRATEGY_DEFAULTS, Disposition, Holding, Plot, build_strategy
from tests.frames import NO_BAR, frame_of, sessions

ETF = "13060"  # 1306
HOLD, EXIT, STAY_OUT = Disposition.HOLD, Disposition.EXIT, Disposition.STAY_OUT
UP, FLAT, DOWN = ("topix_momentum_up",), ("topix_momentum_flat",), ("topix_momentum_down",)
NOT_CHECK_DAY = ("not_check_day",)

CHECK_DAY = date(2025, 10, 1)   # a Wednesday, the first session of October
MID_MONTH = date(2025, 10, 15)  # a Wednesday


def momentum(**params):
    return build_strategy("topix_momentum_v1", params)


def weekdays_through(last: date, count: int) -> list[date]:
    """`count` weekdays up to and including `last`."""
    days, day = [], last
    while len(days) < count:
        if day.weekday() < 5:
            days.insert(0, day)
        day -= timedelta(days=1)
    return days


def last_signal(topix: list[float], on: date, *, held: bool = False, **params):
    """1306's signal on `on`, the last of `topix`'s sessions, from a past
    return over all of them unless told another lookback."""
    days = weekdays_through(on, len(topix))
    frame = frame_of({TOPIX: topix, ETF: [2000.0] * len(topix)}, days)
    strategy = momentum(**{"lookback_sessions": len(topix) - 1, "warmup_sessions": len(topix), **params})
    [signal] = strategy.evaluate(frame, on, [Holding(ETF, 4700, days[0])] if held else [])
    return signal


def judged(topix: list[float], on: date, *, held: bool = False) -> tuple:
    signal = last_signal(topix, on, held=held)
    return signal.disposition, signal.reason_codes


def test_it_buys_1306_on_topix_and_draws_the_past_return_in_a_pane_of_its_own() -> None:
    strategy = momentum()

    assert (strategy.universe_rule, strategy.reference_series) == (UniverseRule.TOPIX_ETF, (TOPIX,))
    assert STRATEGY_DEFAULTS["topix_momentum_v1"] == {"lookback_sessions": 252, "warmup_sessions": 253}
    assert strategy.warmup_sessions == 253
    assert strategy.plots == (Plot("past_return", "separate"),)


def test_on_the_check_day_holding_nothing_it_buys_only_while_the_past_return_is_positive() -> None:
    assert judged([100, 101, 102], CHECK_DAY) == (HOLD, UP)
    assert judged([100, 101, 100], CHECK_DAY) == (STAY_OUT, FLAT)
    assert judged([100, 101, 99], CHECK_DAY) == (STAY_OUT, DOWN)


def test_on_the_check_day_holding_1306_it_sells_only_once_the_past_return_is_negative() -> None:
    assert judged([100, 101, 99], CHECK_DAY, held=True) == (EXIT, DOWN)
    assert judged([100, 101, 100], CHECK_DAY, held=True) == (HOLD, ())
    assert judged([100, 101, 102], CHECK_DAY, held=True) == (HOLD, ())


def test_on_any_other_session_nothing_changes_whichever_way_the_past_return_points() -> None:
    for topix in ([100, 101, 102], [100, 101, 100], [100, 101, 99]):
        assert judged(topix, MID_MONTH) == (STAY_OUT, NOT_CHECK_DAY)
        assert judged(topix, MID_MONTH, held=True) == (HOLD, ())


def test_the_check_day_is_the_first_session_of_the_month_even_when_the_month_opens_on_holidays() -> None:
    """The exchange is shut from 31 December to 3 January (a weekend in
    2026): the first session of January is Monday the 5th, and the 6th is
    not a check day."""
    days = [date(2025, 12, 26), date(2025, 12, 29), date(2025, 12, 30), date(2026, 1, 5), date(2026, 1, 6)]
    frame = frame_of({TOPIX: [100.0, 101.0, 102.0, 103.0, 104.0], ETF: [2000.0] * 5}, days)
    strategy = momentum(lookback_sessions=2, warmup_sessions=3)

    def judged_on(day: date) -> tuple:
        [signal] = strategy.evaluate(frame, day, [])
        return signal.disposition, signal.reason_codes

    assert [judged_on(day) for day in days[2:]] == [(STAY_OUT, NOT_CHECK_DAY), (HOLD, UP), (STAY_OUT, NOT_CHECK_DAY)]


def test_without_a_topix_close_on_the_check_day_the_month_is_not_judged_and_the_next_one_is() -> None:
    """TOPIX rising throughout: no signal on 1 October, the 2nd is not a
    check day for having come after it, and 3 November is judged as usual."""
    days = sessions(28, start=date(2025, 9, 26))  # weekdays to 3 November
    strategy = momentum(lookback_sessions=2, warmup_sessions=3)
    for missing in (NO_BAR, None):
        topix = [100.0 + n for n in range(28)]
        topix[days.index(CHECK_DAY)] = missing
        frame = frame_of({TOPIX: topix, ETF: [2000.0] * 28}, days)

        assert strategy.evaluate(frame, CHECK_DAY, []) == []
        assert strategy.evaluate(frame, CHECK_DAY, [Holding(ETF, 4700, days[0])]) == []
        [the_day_after] = strategy.evaluate(frame, date(2025, 10, 2), [])
        assert (the_day_after.disposition, the_day_after.reason_codes) == (STAY_OUT, NOT_CHECK_DAY)
        [next_month] = strategy.evaluate(frame, date(2025, 11, 3), [])
        assert (next_month.disposition, next_month.reason_codes) == (HOLD, UP)


def test_it_is_ranked_by_the_past_return_and_the_readings_hold_what_is_drawn() -> None:
    signal = last_signal([100, 101, 102], CHECK_DAY)

    assert signal.priority == signal.indicators["past_return"] == pytest.approx(0.02)
    assert signal.indicators == {"topix_close": 102.0, "lookback_close": 100.0,
                                 "past_return": pytest.approx(0.02), "check_day": 1.0}
    assert {plot.indicator for plot in momentum().plots} <= set(signal.indicators)


def test_the_readings_are_worked_out_on_every_session_not_only_the_check_day() -> None:
    signal = last_signal([100, 101, 97], MID_MONTH)

    assert signal.indicators == {"topix_close": 97.0, "lookback_close": 100.0,
                                 "past_return": pytest.approx(-0.03), "check_day": 0.0}


def test_the_lookback_counts_back_over_the_sessions_topix_has_a_close() -> None:
    """A session without one is skipped: two closes back from 106 is 100."""
    days = weekdays_through(CHECK_DAY, 5)
    frame = frame_of({TOPIX: [90.0, 100.0, NO_BAR, 103.0, 106.0], ETF: [2000.0] * 5}, days)

    [signal] = momentum(lookback_sessions=2, warmup_sessions=3).evaluate(frame, CHECK_DAY, [])

    assert (signal.indicators["lookback_close"], signal.indicators["past_return"]) == (100.0, pytest.approx(0.06))


def test_no_signal_until_topix_has_the_lookback_and_the_day_s_own_close() -> None:
    """By default 252 closes back and the day's own: 253. One short,
    nothing; a longer warm-up waits for that many."""
    days = weekdays_through(CHECK_DAY, 253)
    short = frame_of({TOPIX: [100.0] * 252, ETF: [2000.0] * 253}, days)
    enough = frame_of({TOPIX: [100.0] * 253, ETF: [2000.0] * 253}, days)

    assert momentum().evaluate(short, CHECK_DAY, []) == []
    assert len(momentum().evaluate(enough, CHECK_DAY, [])) == 1
    assert momentum(warmup_sessions=254).evaluate(enough, CHECK_DAY, []) == []


def test_no_signal_on_a_session_topix_has_no_close_or_1306_is_halted() -> None:
    days = weekdays_through(MID_MONTH, 4)
    strategy = momentum(lookback_sessions=2, warmup_sessions=3)
    for topix, etf in (([100.0, 101.0, 102.0, NO_BAR], [2000.0] * 4), ([100.0, 101.0, 102.0, None], [2000.0] * 4),
                       ([100.0, 101.0, 102.0, 103.0], [2000.0] * 3 + [None])):
        frame = frame_of({TOPIX: topix, ETF: etf}, days)

        assert strategy.evaluate(frame, MID_MONTH, []) == []
        assert strategy.evaluate(frame, MID_MONTH, [Holding(ETF, 4700, days[0])]) == []


def test_nothing_after_the_day_is_seen() -> None:
    """Judging day t from the whole frame equals judging it from the frame
    cut at t (spec §6.2) — on a TOPIX whose past return turns both ways,
    over nine months of check days."""
    days = sessions(200, start=date(2025, 1, 6))
    topix = [100 + 10 * math.sin(n / 15) for n in range(200)]
    whole = frame_of({TOPIX: topix, ETF: [2000.0] * 200}, days)
    seen = set()

    for day in days[20:]:
        cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
        for holdings in ([], [Holding(ETF, 4700, days[0])]):
            judged_whole = momentum(lookback_sessions=20, warmup_sessions=21).evaluate(whole, day, holdings)
            assert judged_whole == momentum(lookback_sessions=20, warmup_sessions=21).evaluate(cut, day, holdings)
            seen.update((signal.disposition, signal.reason_codes) for signal in judged_whole)

    assert seen == {(HOLD, UP), (STAY_OUT, DOWN), (EXIT, DOWN), (HOLD, ()), (STAY_OUT, NOT_CHECK_DAY)}


def test_an_unknown_parameter_a_warm_up_short_of_the_lookback_or_a_lookback_that_cannot_be_is_refused() -> None:
    with pytest.raises(ValueError, match="ma_sessions"):
        momentum(ma_sessions=200)
    with pytest.raises(ValueError, match="预热期"):
        momentum(warmup_sessions=252)
    with pytest.raises(ValueError, match="预热期"):
        momentum(lookback_sessions=300)  # the warm-up left at 253
    with pytest.raises(ValueError, match="回看长度"):
        momentum(lookback_sessions=0, warmup_sessions=1)
    with pytest.raises(ValueError, match="回看长度"):
        momentum(lookback_sessions=20.5, warmup_sessions=22)
    assert momentum(lookback_sessions=300, warmup_sessions=301).warmup_sessions == 301
