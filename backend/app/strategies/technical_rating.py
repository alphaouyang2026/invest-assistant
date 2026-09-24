"""Technical Rating v1 (spec §6.4, indicators.md §4): the 26 items as
TradingView's TechnicalRating library v3 rates them — see
`.scratch/invest-assistant-v1/tradingview/TechnicalRating-library-v3.pine`,
lines 50–128, which each rule below follows.

The rules judge one security's readings on a session: indicator values
named as below, `[k]` for the value k sessions back.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app import indicators
from app.strategies.base import Bars, Disposition, IndicatorStrategy, Judgement, Plot, Position

DEFAULTS: Mapping[str, Any] = {"warmup_sessions": 260, "entry_above": 0.5, "exit_below": -0.1}
STRONG, WEAK = 0.5, 0.1  # the five bands' edges

MOVING_AVERAGES = tuple(f"{kind}{n}" for kind in ("sma", "ema") for n in (10, 20, 30, 50, 100, 200)) + ("hma9", "vwma20")


@dataclass(frozen=True)
class Rating:
    total: float            # NaN when neither group can be worked out
    moving_averages: float  # NaN when none of its 15 items can
    oscillators: float      # NaN when none of its 11 items can
    items: Mapping[str, int | None]  # +1 / 0 / −1, None when it cannot be worked out


def rate(readings: Mapping[str, float]) -> Rating:
    r = readings
    close = r["close"]
    up_trend, down_trend = close > r["ema50"], close < r["ema50"]

    items: dict[str, int | None] = {}
    for name in MOVING_AVERAGES:
        items[name] = None if _missing(r[name]) else _sign(close - r[name])
    items["ichimoku"] = _item(
        r["span_b"],
        r["span_a[26]"] > r["span_b[26]"] and r["base"] > r["span_a[26]"] and r["conversion"] > r["base"] and close > r["conversion"],
        r["span_a[26]"] < r["span_b[26]"] and r["base"] < r["span_a[26]"] and r["conversion"] < r["base"] and close < r["conversion"],
    )
    moving_averages = _mean(items.values())

    oscillators = {
        "rsi": _item(r["rsi[1]"], r["rsi"] < 30 and r["rsi[1]"] < r["rsi"], r["rsi"] > 70 and r["rsi[1]"] > r["rsi"]),
        "stochastic": _item(
            r["stoch_d[1]"],
            r["stoch_k"] < 20 and r["stoch_d"] < 20 and r["stoch_k"] > r["stoch_d"],
            r["stoch_k"] > 80 and r["stoch_d"] > 80 and r["stoch_k"] < r["stoch_d"],
        ),
        "cci": _item(r["cci[1]"], r["cci"] < -100 and r["cci"] > r["cci[1]"], r["cci"] > 100 and r["cci"] < r["cci[1]"]),
        # Both sides want ADX rising; the support page's "falling" for a sell
        # is not what the library does (indicators.md §4).
        "adx": _item(
            r["adx"],
            r["adx"] > 20 and r["adx"] > r["adx[1]"] and r["plus_di"] > r["minus_di"],
            r["adx"] > 20 and r["adx"] > r["adx[1]"] and r["plus_di"] < r["minus_di"],
        ),
        "awesome_oscillator": _item(
            r["ao[1]"],
            (r["ao"] > 0 and r["ao[1]"] <= 0) or (r["ao"] > 0 and r["ao[1]"] > 0 and r["ao"] > r["ao[1]"] and r["ao[2]"] > r["ao[1]"]),
            (r["ao"] < 0 and r["ao[1]"] >= 0) or (r["ao"] < 0 and r["ao[1]"] < 0 and r["ao"] < r["ao[1]"] and r["ao[2]"] < r["ao[1]"]),
        ),
        "momentum": _item(r["mom[1]"], r["mom"] > r["mom[1]"], r["mom"] < r["mom[1]"]),
        "macd": _item(r["macd_signal"], r["macd"] > r["macd_signal"], r["macd"] < r["macd_signal"]),
        "stoch_rsi": _item(
            r["ema50"],
            down_trend and r["stoch_rsi_k"] < 20 and r["stoch_rsi_d"] < 20 and r["stoch_rsi_k"] > r["stoch_rsi_d"],
            up_trend and r["stoch_rsi_k"] > 80 and r["stoch_rsi_d"] > 80 and r["stoch_rsi_k"] < r["stoch_rsi_d"],
        ),
        "williams_r": _item(r["wr[1]"], r["wr"] < -80 and r["wr"] > r["wr[1]"], r["wr"] > -20 and r["wr"] < r["wr[1]"]),
        "bull_bear_power": _item(
            r["ema50"],
            up_trend and r["bear"] < 0 and r["bear"] > r["bear[1]"],
            down_trend and r["bull"] > 0 and r["bull"] < r["bull[1]"],
        ),
        "ultimate_oscillator": _item(r["uo"], r["uo"] > 70, r["uo"] < 30),
    }
    items |= oscillators
    oscillator_rating = _mean(oscillators.values())

    groups = [g for g in (moving_averages, oscillator_rating) if not math.isnan(g)]
    total = sum(groups) / len(groups) if groups else math.nan
    return Rating(total, moving_averages, oscillator_rating, items)


def band(total: float) -> str:
    """TradingView's five bands; each edge belongs to the milder band."""
    if total > STRONG:
        return "strong_buy"
    if total > WEAK:
        return "buy"
    if total < -STRONG:
        return "strong_sell"
    if total < -WEAK:
        return "sell"
    return "neutral"


def judge_flat(total: float, params: Mapping[str, Any]) -> Judgement:
    """From the side of someone holding none: a rating above the entry line
    can be held, and ranks by the rating."""
    if total > params["entry_above"]:
        return Judgement(Disposition.HOLD, (band(total),), total)
    return Judgement(Disposition.STAY_OUT)


def judge_held(total: float, params: Mapping[str, Any]) -> Judgement:
    """For a position: a rating below the exit line must be sold."""
    if total < params["exit_below"]:
        return Judgement(Disposition.EXIT, (band(total),))
    return Judgement(Disposition.HOLD)


def _item(check: float, bullish: bool, bearish: bool) -> int | None:
    """An item that cannot be worked out — its check value is missing — is
    None and left out of the average. Otherwise a comparison with a missing
    value is simply false, as in Pine."""
    if _missing(check):
        return None
    return 1 if bullish else -1 if bearish else 0


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _missing(value: float | None) -> bool:
    return value is None or math.isnan(value)


def _mean(ratings) -> float:
    counted = [rating for rating in ratings if rating is not None]
    return sum(counted) / len(counted) if counted else math.nan


class TechnicalRating(IndicatorStrategy):
    name = "technical_rating_v1"
    plots = (Plot("rating", "separate"),)

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self.warmup_sessions = self.params["warmup_sessions"]

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        high, low, close, volume, back = bars.high, bars.low, bars.close, bars.volume, bars.back
        lines = {"close": close}
        for n in (10, 20, 30, 50, 100, 200):
            lines[f"sma{n}"], lines[f"ema{n}"] = indicators.sma(close, n), indicators.ema(close, n)
        lines["hma9"] = indicators.hma(close, 9)
        lines["vwma20"] = indicators.vwma(close, volume, 20)
        conversion, base, span_a, span_b = indicators.ichimoku(high, low, 9, 26, 52)
        lines |= {"conversion": conversion, "base": base, "span_b": span_b,
                  "span_a[26]": back(span_a, 26), "span_b[26]": back(span_b, 26)}
        rsi = indicators.rsi(close, 14)
        stoch_k, stoch_d = indicators.stochastic(high, low, close, 14, 3, 3)
        cci = indicators.cci(close, 20)
        plus_di, minus_di, adx = indicators.dmi(high, low, close, 14, 14)
        ao = indicators.awesome_oscillator(high, low, 5, 34)
        mom = indicators.momentum(close, 10)
        macd, macd_signal = indicators.macd(close, 12, 26, 9)
        stoch_rsi_k, stoch_rsi_d = indicators.stoch_rsi(close, 14, 14, 3, 3)
        wr = indicators.williams_r(high, low, close, 14)
        bull, bear = indicators.bull_bear_power(high, low, close, 13)
        lines |= {
            "rsi": rsi, "rsi[1]": back(rsi, 1),
            "stoch_k": stoch_k, "stoch_d": stoch_d, "stoch_d[1]": back(stoch_d, 1),
            "cci": cci, "cci[1]": back(cci, 1),
            "adx": adx, "adx[1]": back(adx, 1), "plus_di": plus_di, "minus_di": minus_di,
            "ao": ao, "ao[1]": back(ao, 1), "ao[2]": back(ao, 2),
            "mom": mom, "mom[1]": back(mom, 1),
            "macd": macd, "macd_signal": macd_signal,
            "stoch_rsi_k": stoch_rsi_k, "stoch_rsi_d": stoch_rsi_d,
            "wr": wr, "wr[1]": back(wr, 1),
            "bull": bull, "bull[1]": back(bull, 1), "bear": bear, "bear[1]": back(bear, 1),
            "uo": indicators.ultimate_oscillator(high, low, close, 7, 14, 28),
        }
        return lines

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        rating = rate(readings)
        readings |= {"rating": rating.total, "rating_ma": rating.moving_averages,
                     "rating_oscillators": rating.oscillators}
        if position is None:
            return judge_flat(rating.total, self.params)
        return judge_held(rating.total, self.params)
