"""Technical Rating v1 against TradingView's own ratings: the screener's
`Recommend.All`, `Recommend.MA` and `Recommend.Other`, and the items it
rates one by one, for eleven Prime stocks on 2026-09-18 (the data is
described in test_indicators_against_tradingview.py).

We follow the TechnicalRating library's source, which the chart indicator
uses. The screener, whose code is not published, differs from it in places
(indicators.md §5): on 150 stocks its Ichimoku vote follows the library's
old v4 rule in 149. Among these eleven that shows once — 9020 — and the
test pins the difference down rather than skipping the stock.

Ratings are averages of whole votes — multiples of 1/330 — so they must
match exactly, not nearly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.market_data import (
    CLOSE, EXEC_CLOSE, EXEC_HIGH, EXEC_LOW, EXEC_OPEN, HIGH, LOW, LOWER_LIMIT_HIT, OPEN, QUALITY,
    TURNOVER, UPPER_LIMIT_HIT, VOLUME, MarketFrame,
)
from app.market_data.frame import COLUMNS
from app.strategies import build_strategy
from app.strategies.technical_rating import rate

DATA = Path(__file__).parent / "data" / "tradingview-2026-09-18"
SNAPSHOT = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))["values"]


@pytest.fixture(scope="module")
def signals():
    rows = pd.read_csv(DATA / "bars.csv.gz", dtype={"code": str}, parse_dates=["date"])
    rows["date"] = rows["date"].dt.date
    data = rows.rename(columns={"open": OPEN, "high": HIGH, "low": LOW, "close": CLOSE, "volume": VOLUME})
    data = data.assign(**{EXEC_OPEN: None, EXEC_HIGH: None, EXEC_LOW: None, EXEC_CLOSE: None, TURNOVER: 1e9,
                          UPPER_LIMIT_HIT: False, LOWER_LIMIT_HIT: False, QUALITY: "ok"})
    frame = MarketFrame(data.set_index(["code", "date"]).sort_index()[COLUMNS])
    day = max(rows["date"])
    return {signal.code: signal for signal in build_strategy("technical_rating_v1", {}).evaluate(frame, day, [])}


ITEMS_THE_SCREENER_SHOWS = {
    "Rec.Stoch.RSI": "stoch_rsi", "Rec.WR": "williams_r", "Rec.BBPower": "bull_bear_power",
    "Rec.UO": "ultimate_oscillator", "Rec.VWMA": "vwma20", "Rec.HullMA9": "hma9",
}
OLD_ICHIMOKU = {"9020"}  # the screener votes 0 by its old rule; the library votes −1


@pytest.mark.parametrize("code", sorted(SNAPSHOT))
def test_the_items_the_screener_shows_match(signals, code) -> None:
    items = rate(signals[code].indicators).items

    assert {theirs: items[ours] for theirs, ours in ITEMS_THE_SCREENER_SHOWS.items()} == {
        theirs: SNAPSHOT[code][theirs] for theirs in ITEMS_THE_SCREENER_SHOWS
    }


@pytest.mark.parametrize("code", sorted(SNAPSHOT))
def test_the_ratings_match_tradingviews(signals, code) -> None:
    ours = signals[code].indicators
    theirs = SNAPSHOT[code]
    ichimoku_gap = 0.0
    if code in OLD_ICHIMOKU:
        assert (rate(ours).items["ichimoku"], theirs["Rec.Ichimoku"]) == (-1, 0)
        ichimoku_gap = -1 / 15

    assert (ours["rating_ma"], ours["rating_oscillators"], ours["rating"]) == pytest.approx(
        (theirs["Recommend.MA"] + ichimoku_gap, theirs["Recommend.Other"], theirs["Recommend.All"] + ichimoku_gap / 2),
        abs=1e-9,
    )
