"""Trend-Pullback v1's rules (spec §6.3, indicators.md §3), judged from one
security's indicator readings on a session — no bars, no database.

`[1]` marks the previous session's value, as in Pine.
"""

from __future__ import annotations

import pytest

from app.strategies import Disposition
from app.strategies.trend_pullback import DEFAULTS, judge_flat, judge_held

# Every entry condition holds, each with a little room to spare.
READY = {
    "close": 105.0, "ema_fast": 104.0, "ema_slow": 100.0,
    "plus_di": 30.0, "minus_di": 18.0, "adx": 25.0, "adx[1]": 24.0,
    "rsi": 32.0, "rsi[1]": 28.0, "atr": 3.0,
}


def test_a_pullback_ending_inside_a_strengthening_uptrend_can_be_held() -> None:
    judgement = judge_flat(READY, DEFAULTS)

    assert judgement.disposition is Disposition.HOLD
    assert judgement.priority == pytest.approx(0.25)  # ADX / 100
    assert judgement.reason_codes == ("ema_uptrend", "dmi_positive", "adx_strengthening", "rsi_recovery")


@pytest.mark.parametrize("missing", [
    {"ema_fast": 100.0},              # EMA20 not above EMA60
    {"close": 100.0},                 # close not above EMA60
    {"plus_di": 18.0},                # +DI not above −DI
    {"adx": 20.0, "adx[1]": 19.0},    # ADX not above 20
    {"adx": 24.0, "adx[1]": 24.5},    # ADX weakening
    {"rsi[1]": 30.5},                 # yesterday was not oversold
    {"rsi": 30.0},                    # today has not left oversold
], ids=["ema", "close", "dmi", "adx_level", "adx_rising", "rsi_was_oversold", "rsi_recovered"])
def test_one_condition_short_and_it_stays_out(missing) -> None:
    judgement = judge_flat(READY | missing, DEFAULTS)

    assert judgement.disposition is Disposition.STAY_OUT
    assert judgement.priority is None


# Held and nothing wrong: the stop sits at 110 − 2 × 3 = 104, below the close.
STEADY = READY | {"rsi": 55.0, "rsi[1]": 50.0}
HIGHEST = 110.0


@pytest.mark.parametrize(("change", "held_for", "reason"), [
    ({"close": 104.0}, 2, "trailing_stop"),                     # close ≤ highest − 2·ATR
    ({"ema_fast": 100.0}, 2, "trend_broken"),                   # EMA20 ≤ EMA60
    ({"plus_di": 18.0}, 2, "trend_broken"),                     # +DI ≤ −DI
    ({"rsi": 71.0, "rsi[1]": 74.0}, 2, "overbought_fade"),      # RSI ≥ 70 and falling
    ({}, 5, "time_exit"),                                       # fifth session held
], ids=["stop", "ema", "dmi", "rsi", "time"])
def test_each_exit_says_it_must_be_sold(change, held_for, reason) -> None:
    judgement = judge_held(STEADY | change, HIGHEST, held_for, DEFAULTS)

    assert judgement.disposition is Disposition.EXIT
    assert judgement.reason_codes == (reason,)


@pytest.mark.parametrize(("change", "reason"), [
    ({"close": 104.0, "ema_fast": 100.0, "rsi": 71.0, "rsi[1]": 74.0}, "trailing_stop"),
    ({"ema_fast": 100.0, "rsi": 71.0, "rsi[1]": 74.0}, "trend_broken"),
    ({"rsi": 71.0, "rsi[1]": 74.0}, "overbought_fade"),
])
def test_several_exits_on_one_day_give_the_first_in_the_specs_order(change, reason) -> None:
    assert judge_held(STEADY | change, HIGHEST, 5, DEFAULTS).reason_codes == (reason,)


def test_nothing_wrong_and_it_can_still_be_held() -> None:
    assert judge_held(STEADY, HIGHEST, 4, DEFAULTS).disposition is Disposition.HOLD


def test_the_inclusive_edges_still_count() -> None:
    """ADX equal to yesterday's is not weakening; RSI exactly 30 yesterday was oversold."""
    assert judge_flat(READY | {"adx[1]": 25.0, "rsi[1]": 30.0}, DEFAULTS).disposition is Disposition.HOLD
