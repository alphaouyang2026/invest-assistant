"""TOPIX moving average v1 (.scratch/topix-etf-strategies spec, ticket 02):
holds 1306 once TOPIX closes more than a band above its moving average,
sells it once TOPIX closes more than the band below, and changes nothing
in between. Judged through `evaluate` on synthetic bars with TOPIX, the
reference series, beside the ETF — no database."""

from __future__ import annotations

import math

import pytest

from app.market_data import TOPIX, MarketFrame, UniverseRule
from app.strategies import STRATEGY_DEFAULTS, Disposition, Holding, Plot, build_strategy
from tests.frames import NO_BAR, frame_of, sessions

ETF = "13060"  # 1306
HOLD, EXIT, STAY_OUT = Disposition.HOLD, Disposition.EXIT, Disposition.STAY_OUT
ABOVE, NEAR, BELOW = ("topix_above_ma",), ("topix_near_ma",), ("topix_below_ma",)


def moving_average(**params):
    return build_strategy("topix_ma_v1", params)


def last_signal(topix: list[float], *, held: bool = False, **params):
    """1306's signal on the last of `topix`'s sessions, from an average over
    all of them unless told another window."""
    days = sessions(len(topix))
    frame = frame_of({TOPIX: topix, ETF: [2000.0] * len(topix)}, days)
    strategy = moving_average(**{"ma_sessions": len(topix), "warmup_sessions": len(topix), **params})
    [signal] = strategy.evaluate(frame, days[-1], [Holding(ETF, 4700, days[0])] if held else [])
    return signal


def judged(topix: list[float], *, held: bool = False, **params) -> tuple:
    signal = last_signal(topix, held=held, **params)
    return signal.disposition, signal.reason_codes


def test_it_buys_1306_on_topix_and_draws_topix_and_its_average_in_a_pane_of_their_own() -> None:
    strategy = moving_average()

    assert (strategy.universe_rule, strategy.reference_series) == (UniverseRule.TOPIX_ETF, (TOPIX,))
    assert STRATEGY_DEFAULTS["topix_ma_v1"] == {"ma_sessions": 200, "band": 0.01, "warmup_sessions": 200}
    assert strategy.warmup_sessions == 200
    assert strategy.plots == (Plot("topix_close", "separate"), Plot("topix_ma", "separate"))


def test_holding_nothing_it_buys_only_once_topix_closes_more_than_1_percent_above_its_average() -> None:
    """Each a two-close average of 100: 101 is exactly on the upper
    threshold and changes nothing; so is 99 on the lower one."""
    assert judged([98.9, 101.1]) == (HOLD, ABOVE)
    assert judged([99, 101]) == (STAY_OUT, NEAR)
    assert judged([100, 100]) == (STAY_OUT, NEAR)
    assert judged([101, 99]) == (STAY_OUT, NEAR)
    assert judged([101.1, 98.9]) == (STAY_OUT, BELOW)


def test_holding_1306_it_sells_only_once_topix_closes_more_than_1_percent_below_its_average() -> None:
    assert judged([101.1, 98.9], held=True) == (EXIT, BELOW)
    assert judged([101, 99], held=True) == (HOLD, ())
    assert judged([100, 100], held=True) == (HOLD, ())
    assert judged([98.9, 101.1], held=True) == (HOLD, ())


def test_with_no_band_it_buys_above_the_average_and_sells_below_it() -> None:
    """A close 0.1% from its average is inside the default band and past a
    band of 0; a close on the average itself changes nothing."""
    assert judged([99.9, 100.1]) == (STAY_OUT, NEAR)
    assert judged([99.9, 100.1], band=0) == (HOLD, ABOVE)
    assert judged([100.1, 99.9], band=0) == (STAY_OUT, BELOW)
    assert judged([100.1, 99.9], held=True, band=0) == (EXIT, BELOW)
    assert judged([100, 100], band=0) == (STAY_OUT, NEAR)
    assert judged([100, 100], held=True, band=0) == (HOLD, ())


def test_it_is_ranked_by_how_far_topix_is_above_its_average_and_the_readings_hold_what_is_drawn() -> None:
    signal = last_signal([98, 102])

    assert signal.priority == signal.indicators["deviation"] == pytest.approx(0.02)
    assert signal.indicators == {"topix_close": 102.0, "topix_ma": 100.0, "deviation": pytest.approx(0.02)}
    assert {plot.indicator for plot in moving_average().plots} <= set(signal.indicators)


def test_no_signal_until_topix_has_as_many_closes_as_the_warm_up() -> None:
    """By default 200, the average's own window: one close short, nothing.
    A longer warm-up waits for that many."""
    days = sessions(200)
    short = frame_of({TOPIX: [100.0] * 199, ETF: [2000.0] * 200}, days)
    enough = frame_of({TOPIX: [100.0] * 200, ETF: [2000.0] * 200}, days)

    assert moving_average().evaluate(short, days[-1], []) == []
    assert len(moving_average().evaluate(enough, days[-1], [])) == 1
    assert moving_average(warmup_sessions=201).evaluate(enough, days[-1], []) == []


def test_the_window_counts_back_over_the_sessions_topix_has_a_close() -> None:
    """A session without one is skipped, as the indicator module does: on
    the last day the average of three is of 100, 103 and 106."""
    days = sessions(5)
    frame = frame_of({TOPIX: [90.0, 100.0, 103.0, NO_BAR, 106.0], ETF: [2000.0] * 5}, days)

    [signal] = moving_average(ma_sessions=3, warmup_sessions=3).evaluate(frame, days[-1], [])

    assert signal.indicators["topix_ma"] == 103.0


def test_no_signal_on_a_session_topix_has_no_close() -> None:
    """Nothing is bought and a holding stays as it is."""
    days = sessions(4)
    strategy = moving_average(ma_sessions=2, warmup_sessions=2)
    for missing in (NO_BAR, None):
        frame = frame_of({TOPIX: [100.0, 100.0, 104.0, missing], ETF: [2000.0] * 4}, days)

        assert strategy.evaluate(frame, days[-1], []) == []
        assert strategy.evaluate(frame, days[-1], [Holding(ETF, 4700, days[0])]) == []


def test_no_signal_on_a_session_1306_is_halted_or_has_no_bar() -> None:
    days = sessions(4)
    strategy = moving_average(ma_sessions=2, warmup_sessions=2)
    for missing in (None, NO_BAR):
        frame = frame_of({TOPIX: [100.0, 100.0, 104.0, 108.0], ETF: [2000.0, 2000.0, 2000.0, missing]}, days)

        assert strategy.evaluate(frame, days[-1], []) == []
        assert strategy.evaluate(frame, days[-1], [Holding(ETF, 4700, days[0])]) == []


def test_topix_is_never_given_a_signal_and_every_other_code_in_the_frame_is() -> None:
    """A stock on the security page, say, is judged on TOPIX's readings as
    1306 is; whether it can be bought is the universe's business."""
    days = sessions(3)
    frame = frame_of({TOPIX: [98.0, 100.0, 102.0], ETF: [2000.0] * 3, "72030": [3000.0] * 3}, days)

    signals = moving_average(ma_sessions=3, warmup_sessions=3).evaluate(frame, days[-1], [])

    assert [(s.code, s.disposition, s.reason_codes) for s in signals] == [(ETF, HOLD, ABOVE), ("72030", HOLD, ABOVE)]


def test_nothing_after_the_day_is_seen() -> None:
    """Judging day t from the whole frame equals judging it from the frame
    cut at t (spec §6.2) — on a TOPIX that crosses its average both ways."""
    days = sessions(300)
    topix = [100 + 10 * math.sin(n / 15) for n in range(300)]
    whole = frame_of({TOPIX: topix, ETF: [2000.0] * 300}, days)
    seen = set()

    for day in days[199:]:
        cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
        for holdings in ([], [Holding(ETF, 4700, days[0])]):
            judged_whole = moving_average().evaluate(whole, day, holdings)
            assert judged_whole == moving_average().evaluate(cut, day, holdings)
            seen.update(signal.reason_codes for signal in judged_whole)

    assert seen == {ABOVE, NEAR, BELOW, ()}


def test_an_unknown_parameter_a_warm_up_shorter_than_the_window_or_a_window_or_band_that_cannot_be_is_refused() -> None:
    with pytest.raises(ValueError, match="lookback_sessions"):
        moving_average(lookback_sessions=252)
    with pytest.raises(ValueError, match="预热期"):
        moving_average(warmup_sessions=199)
    with pytest.raises(ValueError, match="预热期"):
        moving_average(ma_sessions=250)  # the warm-up left at 200
    with pytest.raises(ValueError, match="均线窗口"):
        moving_average(ma_sessions=0, warmup_sessions=1)
    with pytest.raises(ValueError, match="均线窗口"):
        moving_average(ma_sessions=20.5, warmup_sessions=21)
    with pytest.raises(ValueError, match="缓冲带"):
        moving_average(band=-0.01)
    assert moving_average(ma_sessions=250, warmup_sessions=250).warmup_sessions == 250
