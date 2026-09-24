"""The indicator module (spec §5, indicators.md §2): pure functions over one
security's `Series` or a wide frame (rows are sessions, columns codes).

Expected values are worked out by hand from the formulas in indicators.md.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app import indicators

NAN = math.nan


def values(series: pd.Series) -> list[float]:
    return [round(value, 6) if not math.isnan(value) else NAN for value in series]


def same(actual: list[float], expected: list[float]) -> bool:
    return len(actual) == len(expected) and all(
        (math.isnan(a) and math.isnan(e)) or a == pytest.approx(e) for a, e in zip(actual, expected)
    )


def test_sma_is_the_mean_of_the_last_n_bars_and_nan_until_there_are_n() -> None:
    closes = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])

    assert same(values(indicators.sma(closes, 3)), [NAN, NAN, 2.0, 3.0, 4.0])


def test_a_halted_day_is_a_day_without_a_bar_so_the_window_reaches_past_it() -> None:
    closes = pd.Series([1.0, 2.0, NAN, 3.0, 4.0])

    assert same(values(indicators.sma(closes, 2)), [NAN, 1.5, NAN, 2.5, 3.5])


def test_ema_starts_from_the_simple_mean_of_each_codes_own_first_n_bars() -> None:
    """α = 2/(n+1). A: seed (2+4+6)/3 = 4, then ½·20 + ½·4 = 12, ½·10 + ½·12 = 11.
    B listed two days later: seed (3+5)/2 = 4, then ⅔·7 + ⅓·4 = 6."""
    wide = pd.DataFrame({"A": [2.0, 4.0, 6.0, 20.0, 10.0], "B": [NAN, NAN, 3.0, 5.0, 7.0]})

    assert same(values(indicators.ema(wide["A"], 3)), [NAN, NAN, 4.0, 12.0, 11.0])
    assert same(values(indicators.ema(wide, 2)["B"]), [NAN, NAN, NAN, 4.0, 6.0])


def test_rma_smooths_by_one_nth_and_carries_its_state_across_a_halt() -> None:
    """α = 1/3, seed (2+4+6)/3 = 4; the halt changes nothing; then
    ⅓·20 + ⅔·4 = 28/3, ⅓·10 + ⅔·28/3 = 86/9."""
    closes = pd.Series([2.0, 4.0, 6.0, NAN, 20.0, 10.0])

    assert same(values(indicators.rma(closes, 3)), [NAN, NAN, 4.0, NAN, 28 / 3, 86 / 9])


FLAT = pd.Series([5.0] * 6)


@pytest.mark.parametrize(("name", "worked_out"), [
    ("stochastic %K", lambda: indicators.stochastic(FLAT, FLAT, FLAT, 2, 2, 2)[0]),
    ("stochastic %D", lambda: indicators.stochastic(FLAT, FLAT, FLAT, 2, 2, 2)[1]),
    ("Williams %R", lambda: indicators.williams_r(FLAT, FLAT, FLAT, 2)),
    ("CCI", lambda: indicators.cci(FLAT, 3)),
    ("UO", lambda: indicators.ultimate_oscillator(FLAT, FLAT, FLAT, 1, 2, 3)),
    ("VWMA without volume", lambda: indicators.vwma(FLAT, FLAT * 0, 2)),
])
def test_a_zero_denominator_gives_nan(name, worked_out) -> None:
    """Spec §5: an empty range, no deviation, no true range or no volume
    leaves nothing to divide by — NaN, never an infinity or a 0."""
    assert math.isnan(worked_out().iloc[-1]), name


def test_a_wide_frame_gives_each_code_what_it_would_get_alone() -> None:
    """Whether a code is worked out with the whole universe or on its own
    cannot change its numbers — whatever shortcut the wide case takes."""
    steady = [10.0, 12.0, 11.0, 14.0, 13.0, 9.0, 12.0, 15.0, 14.0, 16.0]
    wide = pd.DataFrame({
        "steady": steady,
        "listed_late": [NAN, NAN, NAN, *steady[3:]],
        "halted": [*steady[:4], NAN, NAN, *steady[6:]],
    })
    high, low = wide + 1, wide - 2
    volume = wide * 0 + 100

    def each(frame_result, alone) -> None:
        for code in wide.columns:
            assert same(values(frame_result[code]), values(alone(code))), code

    each(indicators.ema(wide, 3), lambda code: indicators.ema(wide[code], 3))
    each(indicators.rsi(wide, 2), lambda code: indicators.rsi(wide[code], 2))
    each(indicators.hma(wide, 4), lambda code: indicators.hma(wide[code], 4))
    each(indicators.cci(wide, 3), lambda code: indicators.cci(wide[code], 3))
    each(indicators.vwma(wide, volume, 2), lambda code: indicators.vwma(wide[code], volume[code], 2))
    each(indicators.atr(high, low, wide, 2), lambda code: indicators.atr(high[code], low[code], wide[code], 2))
    each(indicators.dmi(high, low, wide, 2, 2)[2], lambda code: indicators.dmi(high[code], low[code], wide[code], 2, 2)[2])
    each(indicators.ultimate_oscillator(high, low, wide, 1, 2, 3),
         lambda code: indicators.ultimate_oscillator(high[code], low[code], wide[code], 1, 2, 3))


def test_rsi_is_wilder_smoothed_gains_over_losses() -> None:
    """n = 2. Changes 2, −1, 2, 0, −4. Gains RMA: 1, 1.5, .75, .375; losses
    RMA: .5, .25, .125, 2.0625. RSI = 100 − 100/(1 + gains/losses)."""
    closes = pd.Series([10.0, 12.0, 11.0, 13.0, 13.0, 9.0])

    assert same(values(indicators.rsi(closes, 2)), [NAN, NAN, 100 - 100 / 3, 100 - 100 / 7, 100 - 100 / 7, 100 - 100 / (1 + 0.375 / 2.0625)])


@pytest.mark.parametrize(("closes", "expected"), [
    ([5.0, 5.0, 5.0, 5.0], 100.0),  # no losses and no gains: 100, as Pine's own check comes first
    ([1.0, 2.0, 3.0, 4.0], 100.0),  # no losses
    ([4.0, 3.0, 2.0, 1.0], 0.0),    # no gains
])
def test_rsi_without_losses_is_100_and_without_gains_is_0(closes, expected) -> None:
    assert values(indicators.rsi(pd.Series(closes), 2))[-1] == expected


def test_atr_is_the_wilder_smoothed_true_range() -> None:
    """True ranges: 10−8 = 2 (no previous close), max(3, 3, 0) = 3,
    max(1, 0, 1) = 1, max(3, 5, 2) = 5. RMA n = 2: 2.5, 1.75, 3.375."""
    high = pd.Series([10.0, 12.0, 11.0, 15.0])
    low = pd.Series([8.0, 9.0, 10.0, 12.0])
    close = pd.Series([9.0, 11.0, 10.0, 14.0])

    assert same(values(indicators.atr(high, low, close, 2)), [NAN, 2.5, 1.75, 3.375])


def test_dmi_gives_plus_di_minus_di_and_adx() -> None:
    """n = 2 for both. From the second bar (Pine's `ta.dmi` uses `ta.tr`,
    which has no value on the first): +DM 2, 0, 4, 0; −DM 0, 0, 0, 1;
    TR 3, 1, 5, 3. RMAs: +DM 1, 2.5, 1.25; −DM 0, 0, .5; TR 2, 3.5, 3.25.
    DX = |+DI − −DI| / (+DI + −DI): 1, 1, 3/7; ADX = 100·RMA(DX): 100, 500/7."""
    high = pd.Series([10.0, 12.0, 11.0, 15.0, 14.0])
    low = pd.Series([8.0, 9.0, 10.0, 12.0, 11.0])
    close = pd.Series([9.0, 11.0, 10.0, 14.0, 12.0])

    plus, minus, adx = indicators.dmi(high, low, close, 2, 2)

    assert same(values(plus), [NAN, NAN, 50.0, 500 / 7, 500 / 13])
    assert same(values(minus), [NAN, NAN, 0.0, 0.0, 200 / 13])
    assert same(values(adx), [NAN, NAN, NAN, 100.0, 500 / 7])


def test_hull_ma_is_a_wma_of_twice_the_half_length_wma_less_the_full_one() -> None:
    """n = 4: WMA(2·WMA(x, 2) − WMA(x, 4), 2), weights 1, 2, … newest last.
    2·WMA2 − WMA4 on the last three bars: 253/30, 253/15, 506/15."""
    closes = pd.Series([1.0, 2.0, 4.0, 8.0, 16.0, 32.0])

    assert same(values(indicators.hma(closes, 4)), [NAN, NAN, NAN, NAN, 253 / 18, 253 / 9])


def test_vwma_weights_each_close_by_its_volume() -> None:
    """n = 2: (10·1 + 20·3) / 4 = 17.5, (20·3 + 30·0) / 3 = 20."""
    close = pd.Series([10.0, 20.0, 30.0])
    volume = pd.Series([1.0, 3.0, 0.0])

    assert same(values(indicators.vwma(close, volume, 2)), [NAN, 17.5, 20.0])


def test_ichimoku_lines_are_midpoints_of_the_highest_high_and_lowest_low() -> None:
    """Lengths 2 / 3 / 4, unshifted (the rating shifts the spans itself).
    Conversion: (12+6)/2, (12+5)/2, (11+5)/2; base: (12+5)/2 twice;
    span A = (conversion + base)/2; span B over 4 bars: (12+5)/2."""
    high = pd.Series([10.0, 12.0, 9.0, 11.0])
    low = pd.Series([6.0, 8.0, 5.0, 9.0])

    conversion, base, span_a, span_b = indicators.ichimoku(high, low, 2, 3, 4)

    assert same(values(conversion), [NAN, 9.0, 8.5, 8.0])
    assert same(values(base), [NAN, NAN, 8.5, 8.5])
    assert same(values(span_a), [NAN, NAN, 8.5, 8.25])
    assert same(values(span_b), [NAN, NAN, NAN, 8.5])


def test_stochastic_k_smooths_where_the_close_sits_in_the_range_and_d_smooths_k() -> None:
    """Periods 2 / 2 / 2. Raw: 100·(11−6)/(12−6) = 250/3, 100·2/5 = 40,
    100·6/6 = 100, 100·1/4 = 25; %K = SMA2: 185/3, 70, 62.5; %D = SMA2 of %K."""
    high = pd.Series([10.0, 12.0, 11.0, 13.0, 12.0])
    low = pd.Series([6.0, 8.0, 7.0, 9.0, 10.0])
    close = pd.Series([8.0, 11.0, 9.0, 13.0, 10.0])

    k, d = indicators.stochastic(high, low, close, 2, 2, 2)

    assert same(values(k), [NAN, NAN, 185 / 3, 70.0, 62.5])
    assert same(values(d), [NAN, NAN, NAN, 395 / 6, 66.25])


def test_cci_measures_the_close_against_its_mean_in_mean_deviations() -> None:
    """n = 3. [10, 12, 14]: mean 12, mean deviation 4/3, (14−12)/(0.015·4/3) = 100.
    [12, 14, 11]: mean 37/3, mean deviation 10/9, (11−37/3)/(0.015·10/9) = −80."""
    closes = pd.Series([10.0, 12.0, 14.0, 11.0])

    assert same(values(indicators.cci(closes, 3)), [NAN, NAN, 100.0, -80.0])


def test_awesome_oscillator_is_a_short_less_a_long_sma_of_the_bar_midpoint() -> None:
    """Lengths 2 / 3 on hl2 = 8, 10, 9, 11: 9.5 − 9 = .5, then 10 − 10 = 0."""
    high = pd.Series([10.0, 12.0, 11.0, 13.0])
    low = pd.Series([6.0, 8.0, 7.0, 9.0])

    assert same(values(indicators.awesome_oscillator(high, low, 2, 3)), [NAN, NAN, 0.5, 0.0])


def test_momentum_is_the_change_over_n_bars() -> None:
    closes = pd.Series([10.0, 12.0, 11.0, 15.0])

    assert same(values(indicators.momentum(closes, 2)), [NAN, NAN, 1.0, 3.0])


def test_macd_is_fast_less_slow_ema_and_the_signal_is_its_ema() -> None:
    """Lengths 2 / 3 / 2 on [2, 4, 6, 20, 10]. EMA2: 3, 5, 15, 35/3; EMA3: 4,
    12, 11. MACD: 1, 3, 2/3. Signal starts at (1+3)/2 = 2, then ⅔·⅔ + ⅓·2 = 10/9."""
    closes = pd.Series([2.0, 4.0, 6.0, 20.0, 10.0])

    line, signal = indicators.macd(closes, 2, 3, 2)

    assert same(values(line), [NAN, NAN, 1.0, 3.0, 2 / 3])
    assert same(values(signal), [NAN, NAN, NAN, 2.0, 10 / 9])


def test_stochastic_rsi_is_the_stochastic_of_the_rsi() -> None:
    """RSI 2 on [10, 12, 11, 14, 13, 9, 12]: 200/3, 800/9, 800/13, 160/9,
    60.2…; where each sits in the last two: 100, 0, 0, 100; K = SMA2: 50,
    0, 50; D = SMA2 of K: 25, 25."""
    closes = pd.Series([10.0, 12.0, 11.0, 14.0, 13.0, 9.0, 12.0])

    k, d = indicators.stoch_rsi(closes, 2, 2, 2, 2)

    assert same(values(k), [NAN, NAN, NAN, NAN, 50.0, 0.0, 50.0])
    assert same(values(d), [NAN, NAN, NAN, NAN, NAN, 25.0, 25.0])


def test_williams_r_is_how_far_the_close_sits_below_the_highest_high() -> None:
    """n = 2: −100·(12−11)/(12−6), −100·(12−9)/(12−7), −100·0/6, −100·(13−10)/(13−9)."""
    high = pd.Series([10.0, 12.0, 11.0, 13.0, 12.0])
    low = pd.Series([6.0, 8.0, 7.0, 9.0, 10.0])
    close = pd.Series([8.0, 11.0, 9.0, 13.0, 10.0])

    assert same(values(indicators.williams_r(high, low, close, 2)), [NAN, -50 / 3, -60.0, 0.0, -75.0])


def test_bull_and_bear_power_are_the_high_and_low_against_the_close_ema() -> None:
    """EMA2 of the close [2, 4, 6, 20, 10]: 3, 5, 15, 35/3."""
    high = pd.Series([3.0, 5.0, 7.0, 21.0, 11.0])
    low = pd.Series([1.0, 3.0, 5.0, 19.0, 9.0])
    close = pd.Series([2.0, 4.0, 6.0, 20.0, 10.0])

    bull, bear = indicators.bull_bear_power(high, low, close, 2)

    assert same(values(bull), [NAN, 2.0, 2.0, 6.0, -2 / 3])
    assert same(values(bear), [NAN, 0.0, 0.0, 4.0, -8 / 3])


def test_ultimate_oscillator_weights_three_buying_pressure_averages_4_2_1() -> None:
    """Lengths 1 / 2 / 3. From the second bar (no previous close before it):
    buying pressure close − min(low, close[1]) = 2, 0, 4; true range 3, 1, 5.
    Averages on the last bar: 4/5, 4/6, 6/9; UO = 100·(4·.8 + 2·⅔ + ⅔)/7 = 520/7."""
    high = pd.Series([10.0, 12.0, 11.0, 15.0])
    low = pd.Series([8.0, 9.0, 10.0, 12.0])
    close = pd.Series([9.0, 11.0, 10.0, 14.0])

    assert same(values(indicators.ultimate_oscillator(high, low, close, 1, 2, 3)), [NAN, NAN, NAN, 520 / 7])
