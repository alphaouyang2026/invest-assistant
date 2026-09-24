"""Synthetic bars as a `MarketFrame`, for strategy tests that need no
database (issue 03: 策略测试只用合成 K 线).

Each code's closes line up with the *last* sessions, so a shorter list is a
later listing. `None` is an untradable bar (a halt: the bar exists, its
prices do not); `NO_BAR` is a session with no bar at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from app.market_data import (
    CLOSE, EXEC_CLOSE, EXEC_HIGH, EXEC_LOW, EXEC_OPEN, HIGH, LOW, LOWER_LIMIT_HIT, OPEN, QUALITY,
    TURNOVER, UPPER_LIMIT_HIT, VOLUME, MarketFrame,
)
from app.market_data.frame import CODE, COLUMNS, DATE

NO_BAR = object()


def sessions(count: int, start: date = date(2025, 1, 6)) -> list[date]:
    """`count` weekdays from `start`."""
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def frame_of(closes: Mapping[str, Sequence[float | None | object]], days: Sequence[date]) -> MarketFrame:
    """Flat bars around each close: open at the close, high 1% above, low
    1% below, a million shares."""
    rows = []
    for code, series in closes.items():
        for day, close in zip(days[len(days) - len(series):], series):
            if close is NO_BAR:
                continue
            rows.append(_bar(code, day, close))
    data = pd.DataFrame(rows).set_index([CODE, DATE]).sort_index()
    return MarketFrame(data[COLUMNS])


def _bar(code: str, day: date, close: float | None) -> dict:
    if close is None:
        research = dict.fromkeys((OPEN, HIGH, LOW, CLOSE, VOLUME), float("nan"))
        execution = dict.fromkeys((EXEC_OPEN, EXEC_HIGH, EXEC_LOW, EXEC_CLOSE))
        quality = "untradable"
    else:
        research = {OPEN: close, HIGH: close * 1.01, LOW: close * 0.99, CLOSE: close, VOLUME: 1e6}
        execution = {EXEC_OPEN: Decimal(str(close)), EXEC_HIGH: Decimal(str(close * 1.01)),
                     EXEC_LOW: Decimal(str(close * 0.99)), EXEC_CLOSE: Decimal(str(close))}
        quality = "ok"
    return {CODE: code, DATE: day, **research, **execution, TURNOVER: 1e9,
            UPPER_LIMIT_HIT: False, LOWER_LIMIT_HIT: False, QUALITY: quality}
