"""Long trend v1 (ticket 05 A, spec §6.6): on the first session of each
month — its check day — a Prime stock can be held while its close is above
its own simple moving average and must be sold once it is not; on every
other session nothing changes. Judged through `evaluate` on synthetic bars —
no database."""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.market_data import MarketFrame, UniverseRule
from app.strategies import STRATEGY_DEFAULTS, Disposition, Holding, Plot, WarmupFollows, build_strategy
from tests.frames import NO_BAR, frame_of, sessions, weekdays_through

HOLD, EXIT, STAY_OUT = Disposition.HOLD, Disposition.EXIT, Disposition.STAY_OUT
ABOVE, NOT_ABOVE, NOT_CHECK_DAY = ("above_sma",), ("not_above_sma",), ("not_check_day",)

CHECK_DAY = date(2025, 10, 1)   # a Wednesday, the first session of October
MID_MONTH = date(2025, 10, 15)  # a Wednesday


def long_trend(**params):
    return build_strategy("long_trend_v1", params)


def judged(closes: list[float], on: date, *, held: bool = False) -> tuple:
    """Stock A's signal on `on`, the last of `closes`' sessions, against the
    average of all of them."""
    days = weekdays_through(on, len(closes))
    strategy = long_trend(sma_sessions=len(closes), warmup_sessions=len(closes))
    holdings = [Holding("A", 100, days[0])] if held else []
    [signal] = strategy.evaluate(frame_of({"A": closes}, days), on, holdings)
    return signal.disposition, signal.reason_codes


def test_it_buys_prime_stocks_on_their_own_bars_and_draws_the_average_on_the_price() -> None:
    strategy = long_trend()

    assert STRATEGY_DEFAULTS["long_trend_v1"] == {"sma_sessions": 200, "warmup_sessions": 200}
    assert (strategy.universe_rule, strategy.reference_series) == (UniverseRule.PRIME_COMMON_STOCK, ())
    assert strategy.warmup_sessions == 200
    assert strategy.warmup_follows == WarmupFollows("sma_sessions", 0)
    assert strategy.plots == (Plot("sma", "price"),)
    assert strategy.ranks_holdings is False


def test_on_the_check_day_holding_nothing_it_buys_only_a_close_above_the_average() -> None:
    assert judged([100, 101, 105], CHECK_DAY) == (HOLD, ABOVE)       # average 102
    assert judged([101, 99, 100], CHECK_DAY) == (STAY_OUT, NOT_ABOVE)  # exactly on it
    assert judged([104, 102, 100], CHECK_DAY) == (STAY_OUT, NOT_ABOVE)


def test_on_the_check_day_holding_it_sells_once_the_close_is_not_above_the_average() -> None:
    assert judged([104, 102, 100], CHECK_DAY, held=True) == (EXIT, NOT_ABOVE)
    assert judged([101, 99, 100], CHECK_DAY, held=True) == (EXIT, NOT_ABOVE)
    assert judged([100, 101, 105], CHECK_DAY, held=True) == (HOLD, ())


def test_on_any_other_session_nothing_changes_whichever_side_of_the_average_the_close_is() -> None:
    for closes in ([100, 101, 105], [101, 99, 100], [104, 102, 100]):
        assert judged(closes, MID_MONTH) == (STAY_OUT, NOT_CHECK_DAY)
        assert judged(closes, MID_MONTH, held=True) == (HOLD, ())


def test_it_is_ranked_by_how_far_the_close_is_above_the_average() -> None:
    days = weekdays_through(CHECK_DAY, 3)
    frame = frame_of({"A": [100.0, 101.0, 105.0], "B": [100.0, 100.0, 130.0], "C": [100.0, 100.0, 90.0]}, days)

    signals = long_trend(sma_sessions=3, warmup_sessions=3).evaluate(frame, CHECK_DAY, [])

    assert [(s.code, s.disposition) for s in signals] == [("A", HOLD), ("B", HOLD), ("C", STAY_OUT)]
    a, b, _ = signals
    assert a.priority == a.indicators["deviation"] == pytest.approx(105 / 102 - 1)
    assert b.priority == pytest.approx(130 / 110 - 1)
    assert a.indicators == {"close": 105.0, "sma": 102.0, "deviation": pytest.approx(105 / 102 - 1),
                            "check_day": 1.0}


def test_the_check_day_is_the_first_session_of_the_month_even_when_the_month_opens_on_holidays() -> None:
    days = [date(2025, 12, 26), date(2025, 12, 29), date(2025, 12, 30), date(2026, 1, 5), date(2026, 1, 6)]
    frame = frame_of({"A": [100.0, 101.0, 102.0, 103.0, 104.0]}, days)
    strategy = long_trend(sma_sessions=3, warmup_sessions=3)

    def judged_on(day: date) -> tuple:
        [signal] = strategy.evaluate(frame, day, [])
        return signal.disposition, signal.reason_codes

    assert [judged_on(day) for day in days[2:]] == [(STAY_OUT, NOT_CHECK_DAY), (HOLD, ABOVE), (STAY_OUT, NOT_CHECK_DAY)]


def test_a_stock_halted_on_the_check_day_is_not_judged_that_month() -> None:
    """Another stock trades, so 1 October is still the check day: A has no
    signal — held, it is kept — and 2 October is no check day for A either."""
    days = sessions(8, start=date(2025, 9, 24))  # to 3 October
    frame = frame_of({"A": [100.0, 101.0, 102.0, 103.0, 104.0, None, 106.0, 107.0], "B": [50.0] * 8}, days)
    strategy = long_trend(sma_sessions=3, warmup_sessions=3)

    assert [s.code for s in strategy.evaluate(frame, CHECK_DAY, [Holding("A", 100, days[0])])] == ["B"]
    [a, _] = strategy.evaluate(frame, date(2025, 10, 2), [])
    assert (a.code, a.reason_codes) == ("A", NOT_CHECK_DAY)


def test_the_average_counts_back_over_the_sessions_the_stock_has_a_bar() -> None:
    days = weekdays_through(CHECK_DAY, 5)
    frame = frame_of({"A": [90.0, 100.0, NO_BAR, 103.0, 106.0], "B": [50.0] * 5}, days)

    [a, _] = long_trend(sma_sessions=3, warmup_sessions=3).evaluate(frame, CHECK_DAY, [])

    assert a.indicators["sma"] == pytest.approx((100 + 103 + 106) / 3)


def test_no_signal_until_the_stock_has_the_warm_up_s_worth_of_bars() -> None:
    days = weekdays_through(CHECK_DAY, 200)
    frame = frame_of({"short": [100.0] * 199, "enough": [100.0] * 200}, days)

    assert [s.code for s in long_trend().evaluate(frame, CHECK_DAY, [])] == ["enough"]
    assert long_trend(warmup_sessions=201).evaluate(frame, CHECK_DAY, []) == []


def test_nothing_after_the_day_is_seen() -> None:
    """Judging day t from the whole frame equals judging it from the frame
    cut at t (spec §6.2), over nine months of check days."""
    days = sessions(200, start=date(2025, 1, 6))
    whole = frame_of({"A": [100 + 10 * math.sin(n / 15) for n in range(200)],
                      "B": [100 + 10 * math.cos(n / 9) for n in range(200)]}, days)
    seen = set()

    for day in days[20:]:
        cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
        for holdings in ([], [Holding("A", 100, days[0]), Holding("B", 100, days[0])]):
            judged_whole = long_trend(sma_sessions=20, warmup_sessions=20).evaluate(whole, day, holdings)
            assert judged_whole == long_trend(sma_sessions=20, warmup_sessions=20).evaluate(cut, day, holdings)
            seen.update((signal.disposition, signal.reason_codes) for signal in judged_whole)

    assert seen == {(HOLD, ABOVE), (STAY_OUT, NOT_ABOVE), (EXIT, NOT_ABOVE), (HOLD, ()), (STAY_OUT, NOT_CHECK_DAY)}


def test_an_unknown_parameter_a_warm_up_short_of_the_window_or_a_window_that_cannot_be_is_refused() -> None:
    with pytest.raises(ValueError, match="lookback_sessions"):
        long_trend(lookback_sessions=200)
    with pytest.raises(ValueError, match="预热期"):
        long_trend(warmup_sessions=199)
    with pytest.raises(ValueError, match="均线窗口"):
        long_trend(sma_sessions=0, warmup_sessions=1)
    with pytest.raises(ValueError, match="均线窗口"):
        long_trend(sma_sessions=20.5, warmup_sessions=21)
    assert long_trend(sma_sessions=120, warmup_sessions=120).warmup_sessions == 120
