"""Trend-Pullback v1 (spec §6.3, indicators.md §3).

The rules judge one security's readings on a session: indicator values
named as below, `[1]` for the previous session's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from app import indicators
from app.strategies.base import Bars, Disposition, IndicatorStrategy, Judgement, Plot, Position

DEFAULTS: Mapping[str, Any] = {
    "warmup_sessions": 180,  # three times EMA60's length
    "ema_fast": 20, "ema_slow": 60, "di_length": 14, "adx_length": 14, "adx_min": 20,
    "rsi_length": 14, "rsi_oversold": 30, "rsi_overbought": 70,
    "atr_length": 14, "atr_multiple": 2, "max_holding_sessions": 5,
}
ENTRY_REASONS = ("ema_uptrend", "dmi_positive", "adx_strengthening", "rsi_recovery")


def judge_flat(readings: Mapping[str, float], params: Mapping[str, Any]) -> Judgement:
    """From the side of someone holding none: can it be held?"""
    r = readings
    ready = (
        r["ema_fast"] > r["ema_slow"] and r["close"] > r["ema_slow"]
        and r["plus_di"] > r["minus_di"]
        and r["adx"] > params["adx_min"] and r["adx"] >= r["adx[1]"]
        and r["rsi[1]"] <= params["rsi_oversold"] < r["rsi"]
    )
    if not ready:
        return Judgement(Disposition.STAY_OUT)
    return Judgement(Disposition.HOLD, ENTRY_REASONS, r["adx"] / 100)


def judge_held(
    readings: Mapping[str, float], highest_close: float, sessions_held: int, params: Mapping[str, Any],
) -> Judgement:
    """For a position: must it be sold? The first exit that applies, in
    the spec's order, is the reason. `highest_close` is the highest research
    close since it was bought; the day it was bought counts as session 1."""
    r = readings
    exits = (
        ("trailing_stop", r["close"] <= highest_close - params["atr_multiple"] * r["atr"]),
        ("trend_broken", r["ema_fast"] <= r["ema_slow"] or r["plus_di"] <= r["minus_di"]),
        ("overbought_fade", r["rsi"] >= params["rsi_overbought"] and r["rsi"] < r["rsi[1]"]),
        ("time_exit", sessions_held >= params["max_holding_sessions"]),
    )
    for reason, applies in exits:
        if applies:
            return Judgement(Disposition.EXIT, (reason,))
    return Judgement(Disposition.HOLD)


class TrendPullback(IndicatorStrategy):
    name = "trend_pullback_v1"
    plots = (
        Plot("ema_fast", "price"), Plot("ema_slow", "price"),
        Plot("rsi", "separate"), Plot("adx", "separate"), Plot("plus_di", "separate"), Plot("minus_di", "separate"),
    )

    def __init__(self, params: Mapping[str, Any]) -> None:
        super().__init__({**DEFAULTS, **params})
        self.warmup_sessions = self.params["warmup_sessions"]

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        p, close = self.params, bars.close
        plus_di, minus_di, adx = indicators.dmi(bars.high, bars.low, close, p["di_length"], p["adx_length"])
        rsi = indicators.rsi(close, p["rsi_length"])
        return {
            "close": close,
            "ema_fast": indicators.ema(close, p["ema_fast"]), "ema_slow": indicators.ema(close, p["ema_slow"]),
            "plus_di": plus_di, "minus_di": minus_di, "adx": adx, "adx[1]": bars.back(adx, 1),
            "rsi": rsi, "rsi[1]": bars.back(rsi, 1),
            "atr": indicators.atr(bars.high, bars.low, close, p["atr_length"]),
        }

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        if position is None:
            return judge_flat(readings, self.params)
        return judge_held(readings, position.highest_close, position.sessions_held, self.params)
