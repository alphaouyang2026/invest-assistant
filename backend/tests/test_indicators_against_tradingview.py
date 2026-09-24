"""Indicators against TradingView's own numbers (indicators.md §5).

`tests/data/tradingview-2026-09-18/` holds, for eleven Prime stocks spread
across the five rating bands:
- `bars.csv.gz`: their last 1,000 sessions to 2026-09-18, research prices
  read from the 02 backfill with `MarketData.read`;
- `snapshot.json`: what TradingView's screener
  (`POST https://scanner.tradingview.com/japan/scan`) reported for them on
  2026-09-18, fetched 2026-09-24.

A thousand sessions is enough for EMA200 to forget where it started: with
the full five years the worst difference is 3e-6, with 1,000 it is 6e-6.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app import indicators

DATA = Path(__file__).parent / "data" / "tradingview-2026-09-18"
SNAPSHOT = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))["values"]
CODES = sorted(SNAPSHOT)
CLOSE_ENOUGH = 1e-4  # relative


@pytest.fixture(scope="module")
def bars() -> dict[str, pd.DataFrame]:
    rows = pd.read_csv(DATA / "bars.csv.gz", dtype={"code": str}, parse_dates=["date"])
    return {field: rows.pivot(index="date", columns="code", values=field)
            for field in ("open", "high", "low", "close", "volume")}


@pytest.fixture(scope="module")
def ours(bars) -> dict[str, pd.DataFrame]:
    """Every indicator TradingView reports, keyed by its screener column."""
    high, low, close, volume = bars["high"], bars["low"], bars["close"], bars["volume"]
    lines: dict[str, pd.DataFrame] = {}
    for n in (10, 20, 30, 50, 100, 200):
        lines[f"EMA{n}"] = indicators.ema(close, n)
        lines[f"SMA{n}"] = indicators.sma(close, n)
    lines["HullMA9"] = indicators.hma(close, 9)
    lines["VWMA"] = indicators.vwma(close, volume, 20)
    conversion, base, span_a, span_b = indicators.ichimoku(high, low, 9, 26, 52)
    lines["Ichimoku.CLine"], lines["Ichimoku.BLine"] = conversion, base
    # The screener's spans are the chart's: drawn 26 bars ahead counting
    # the bar itself, so today's are the ones worked out 25 bars ago.
    lines["Ichimoku.Lead1"], lines["Ichimoku.Lead2"] = span_a.shift(25), span_b.shift(25)
    lines["RSI"] = indicators.rsi(close, 14)
    lines["Stoch.K"], lines["Stoch.D"] = indicators.stochastic(high, low, close, 14, 3, 3)
    # The screener's CCI takes hlc3; the rating library's takes the close.
    lines["CCI20"] = indicators.cci((high + low + close) / 3, 20)
    lines["ADX+DI"], lines["ADX-DI"], lines["ADX"] = indicators.dmi(high, low, close, 14, 14)
    lines["AO"] = indicators.awesome_oscillator(high, low, 5, 34)
    lines["Mom"] = indicators.momentum(close, 10)
    lines["MACD.macd"], lines["MACD.signal"] = indicators.macd(close, 12, 26, 9)
    lines["Stoch.RSI.K"], _ = indicators.stoch_rsi(close, 14, 14, 3, 3)
    lines["W.R"] = indicators.williams_r(high, low, close, 14)
    bull, bear = indicators.bull_bear_power(high, low, close, 13)
    lines["BBPower"] = bull + bear  # TradingView's Bull Bear Power plots the sum
    lines["UO"] = indicators.ultimate_oscillator(high, low, close, 7, 14, 28)
    lines["ATR"] = indicators.atr(high, low, close, 14)
    return lines


# The screener's previous-session Stochastic matches nothing in the series
# (not %K or %D, smoothed or raw, a bar or two back) while today's matches
# exactly, so it is left out. The rating only asks whether yesterday's %D
# exists, never its value.
UNEXPLAINED = ("Stoch.K[1]", "Stoch.D[1]")
REPORTED = [
    column for column in json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))["columns"]
    if column not in ("time", "open", "high", "low", "close", "volume", *UNEXPLAINED)
    and not column.startswith(("Rec.", "Recommend."))
]


@pytest.mark.parametrize("column", REPORTED)
def test_each_indicator_matches_tradingview_on_the_last_session(ours, column) -> None:
    name, _, back = column.partition("[")
    bars_back = int(back.rstrip("]")) if back else 0
    mismatches = {}
    for code in CODES:
        expected = SNAPSHOT[code][column]
        actual = ours[name][code].iloc[-1 - bars_back]
        if actual != pytest.approx(expected, rel=CLOSE_ENOUGH, abs=1e-9):
            mismatches[code] = (actual, expected)
    assert not mismatches, f"{column}: ours vs TradingView {mismatches}"
