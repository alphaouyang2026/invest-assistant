"""Technical Rating v1's rules (spec §6.4, indicators.md §4): the 26 items
as TradingView's TechnicalRating library v3 rates them, from one
security's readings on a session.

`[1]`, `[2]` and `[26]` mark values that many sessions back, as in Pine.
"""

from __future__ import annotations

import pytest

from app.strategies import Disposition
from app.strategies.technical_rating import DEFAULTS, band, judge_flat, judge_held, rate

MOVING_AVERAGES = [f"{kind}{n}" for kind in ("sma", "ema") for n in (10, 20, 30, 50, 100, 200)] + ["hma9", "vwma20"]

# Every item neutral: each average on the close, no cloud either way, every
# oscillator in the middle and flat, the close on its EMA50 (no trend).
NEUTRAL = {
    "close": 100.0,
    **{name: 100.0 for name in MOVING_AVERAGES},
    "conversion": 100.0, "base": 100.0, "span_a[26]": 100.0, "span_b[26]": 100.0, "span_b": 100.0,
    "rsi": 50.0, "rsi[1]": 50.0,
    "stoch_k": 50.0, "stoch_d": 50.0, "stoch_d[1]": 50.0,
    "cci": 0.0, "cci[1]": 0.0,
    "adx": 15.0, "adx[1]": 15.0, "plus_di": 20.0, "minus_di": 20.0,
    "ao": 0.0, "ao[1]": 0.0, "ao[2]": 0.0,
    "mom": 0.0, "mom[1]": 0.0,
    "macd": 0.0, "macd_signal": 0.0,
    "stoch_rsi_k": 50.0, "stoch_rsi_d": 50.0, "ema50": 100.0,
    "wr": -50.0, "wr[1]": -50.0,
    "bull": 0.0, "bull[1]": 0.0, "bear": 0.0, "bear[1]": 0.0,
    "uo": 50.0,
}


def test_all_26_items_neutral_rate_zero() -> None:
    rating = rate(NEUTRAL)

    assert (rating.total, rating.moving_averages, rating.oscillators) == (0.0, 0.0, 0.0)
    assert len(rating.items) == 26 and set(rating.items.values()) == {0}


@pytest.mark.parametrize("average", MOVING_AVERAGES)
def test_each_moving_average_buys_below_the_close_and_sells_above_it(average) -> None:
    assert rate(NEUTRAL | {average: 99.0}).items[average] == 1
    assert rate(NEUTRAL | {average: 101.0}).items[average] == -1


BULLISH_CLOUD = {"span_a[26]": 95.0, "span_b[26]": 90.0, "base": 97.0, "conversion": 99.0}
BEARISH_CLOUD = {"span_a[26]": 105.0, "span_b[26]": 110.0, "base": 103.0, "conversion": 101.0}
DOWN_TREND, UP_TREND = {"ema50": 105.0}, {"ema50": 95.0}


@pytest.mark.parametrize(("item", "change", "expected"), [
    ("ichimoku", BULLISH_CLOUD, 1),
    ("ichimoku", BEARISH_CLOUD, -1),
    ("ichimoku", BULLISH_CLOUD | {"conversion": 96.0}, 0),                          # one of four short
    ("rsi", {"rsi": 28.0, "rsi[1]": 25.0}, 1),
    ("rsi", {"rsi": 72.0, "rsi[1]": 75.0}, -1),
    ("rsi", {"rsi": 28.0, "rsi[1]": 29.0}, 0),                                      # oversold but still falling
    ("stochastic", {"stoch_k": 15.0, "stoch_d": 10.0}, 1),
    ("stochastic", {"stoch_k": 85.0, "stoch_d": 90.0}, -1),
    ("stochastic", {"stoch_k": 15.0, "stoch_d": 18.0}, 0),
    ("cci", {"cci": -120.0, "cci[1]": -130.0}, 1),
    ("cci", {"cci": 120.0, "cci[1]": 130.0}, -1),
    ("adx", {"adx": 25.0, "adx[1]": 24.0, "plus_di": 30.0, "minus_di": 20.0}, 1),
    ("adx", {"adx": 25.0, "adx[1]": 24.0, "plus_di": 20.0, "minus_di": 30.0}, -1),
    ("adx", {"adx": 25.0, "adx[1]": 26.0, "plus_di": 20.0, "minus_di": 30.0}, 0),   # the support page would say sell
    ("awesome_oscillator", {"ao": 1.0, "ao[1]": -1.0}, 1),                          # crosses above 0
    ("awesome_oscillator", {"ao": 3.0, "ao[1]": 2.0, "ao[2]": 4.0}, 1),             # above 0, turns up
    ("awesome_oscillator", {"ao": -1.0, "ao[1]": 1.0}, -1),                         # crosses below 0
    ("awesome_oscillator", {"ao": -3.0, "ao[1]": -2.0, "ao[2]": -4.0}, -1),         # below 0, turns down
    ("momentum", {"mom": 2.0, "mom[1]": 1.0}, 1),
    ("momentum", {"mom": 1.0, "mom[1]": 2.0}, -1),
    ("macd", {"macd": 1.0}, 1),
    ("macd", {"macd": -1.0}, -1),
    ("stoch_rsi", DOWN_TREND | {"stoch_rsi_k": 15.0, "stoch_rsi_d": 10.0}, 1),
    ("stoch_rsi", UP_TREND | {"stoch_rsi_k": 85.0, "stoch_rsi_d": 90.0}, -1),
    ("stoch_rsi", {"stoch_rsi_k": 15.0, "stoch_rsi_d": 10.0}, 0),                   # no downtrend
    ("williams_r", {"wr": -85.0, "wr[1]": -90.0}, 1),
    ("williams_r", {"wr": -15.0, "wr[1]": -10.0}, -1),
    ("bull_bear_power", UP_TREND | {"bear": -1.0, "bear[1]": -2.0}, 1),
    ("bull_bear_power", DOWN_TREND | {"bull": 1.0, "bull[1]": 2.0}, -1),
    ("bull_bear_power", {"bear": -1.0, "bear[1]": -2.0}, 0),                        # no uptrend
    ("ultimate_oscillator", {"uo": 75.0}, 1),
    ("ultimate_oscillator", {"uo": 25.0}, -1),
])
def test_each_oscillator_and_the_cloud_rate_as_the_library_does(item, change, expected) -> None:
    assert rate(NEUTRAL | change).items[item] == expected


NAN = float("nan")


def test_an_item_whose_check_value_is_missing_is_left_out_of_the_average() -> None:
    """SMA200 and the cloud (checked on span B) cannot be worked out, so the
    moving-average group is SMA10's +1 over the 13 items left."""
    rating = rate(NEUTRAL | {"sma200": NAN, "span_b": NAN, "sma10": 99.0})

    assert rating.items["sma200"] is None and rating.items["ichimoku"] is None
    assert rating.moving_averages == pytest.approx(1 / 13)


def test_an_item_with_its_check_value_but_another_value_missing_counts_as_neutral() -> None:
    """RSI's check value is yesterday's RSI; with today's missing, both of its
    comparisons are simply false — neutral, and still counted."""
    rating = rate(NEUTRAL | {"rsi": NAN, "macd": 1.0})

    assert rating.items["rsi"] == 0
    assert rating.oscillators == pytest.approx(1 / 11)


def test_the_total_is_the_mean_of_the_two_groups() -> None:
    all_averages_buy = {name: 99.0 for name in MOVING_AVERAGES} | BULLISH_CLOUD
    rating = rate(NEUTRAL | all_averages_buy | {"uo": 25.0})

    assert (rating.moving_averages, rating.oscillators) == (1.0, pytest.approx(-1 / 11))
    assert rating.total == pytest.approx((1 - 1 / 11) / 2)


def test_with_one_group_missing_entirely_the_total_is_the_other() -> None:
    no_oscillators = {key: NAN for key in ("rsi[1]", "stoch_d[1]", "cci[1]", "adx", "ao[1]", "mom[1]",
                                           "macd_signal", "ema50", "wr[1]", "uo")}
    rating = rate(NEUTRAL | no_oscillators | {"sma10": 99.0})

    # EMA50 is also a moving-average item, so that group is SMA10's +1 over 14.
    assert rating.total == pytest.approx(1 / 14)


@pytest.mark.parametrize(("total", "expected"), [
    (0.51, "strong_buy"), (0.5, "buy"),
    (0.11, "buy"), (0.1, "neutral"),
    (-0.1, "neutral"), (-0.11, "sell"),
    (-0.5, "sell"), (-0.51, "strong_sell"),
])
def test_the_five_bands_and_their_edges(total, expected) -> None:
    assert band(total) == expected


def test_a_strong_buy_can_be_held_and_ranks_by_its_rating() -> None:
    judgement = judge_flat(0.51, DEFAULTS)

    assert judgement.disposition is Disposition.HOLD
    assert judgement.priority == 0.51 and judgement.reason_codes == ("strong_buy",)
    assert judge_flat(0.5, DEFAULTS).disposition is Disposition.STAY_OUT


def test_a_position_must_be_sold_once_the_rating_falls_below_minus_point_one() -> None:
    judgement = judge_held(-0.11, DEFAULTS)

    assert judgement.disposition is Disposition.EXIT and judgement.reason_codes == ("sell",)
    assert judge_held(-0.1, DEFAULTS).disposition is Disposition.HOLD
