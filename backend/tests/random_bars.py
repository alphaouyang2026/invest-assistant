"""Random-walk bars as a `MarketFrame`, for the model experiment tests:
prices, ranges, volume and turnover that move, so every feature varies.
Seeded, so the same call gives the same bars."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from app.market_data import (
    ADJUSTMENT_FACTOR, CLOSE, EX_RIGHTS_TYPE, EXEC_CLOSE, EXEC_HIGH, EXEC_LOW, EXEC_OPEN, HIGH, LOW, LOWER_LIMIT_HIT,
    OPEN, QUALITY, TURNOVER, UPPER_LIMIT_HIT, VOLUME, MarketFrame,
)
from app.market_data.frame import CODE, COLUMNS, DATE


def walk(codes: Sequence[str], days: Sequence[date], seed: int = 0) -> list[dict]:
    """A bar per code per day, as rows `frame_from` takes."""
    rng = np.random.default_rng(seed)
    rows = []
    for code in codes:
        close = float(rng.uniform(500, 3000))
        for day in days:
            close *= math.exp(rng.normal(0, 0.02))
            opened = close * math.exp(rng.normal(0, 0.01))
            high = max(opened, close) * (1 + abs(rng.normal(0, 0.01)))
            low = min(opened, close) * (1 - abs(rng.normal(0, 0.01)))
            volume = float(rng.integers(100_000, 2_000_000))
            rows.append({CODE: code, DATE: day, OPEN: opened, HIGH: high, LOW: low, CLOSE: close, VOLUME: volume,
                         TURNOVER: volume * close})
    return rows


def frame_from(rows: Sequence[dict]) -> MarketFrame:
    """Rows of research prices (`None` prices: an untradable bar) as a
    frame, with execution prices to match."""
    full = []
    for row in rows:
        halted = row[CLOSE] is None
        prices = {column: (math.nan if halted else row[column]) for column in (OPEN, HIGH, LOW, CLOSE, VOLUME)}
        execution = {exec_column: None if halted else Decimal(str(round(row[column], 1)))
                     for exec_column, column in ((EXEC_OPEN, OPEN), (EXEC_HIGH, HIGH), (EXEC_LOW, LOW),
                                                 (EXEC_CLOSE, CLOSE))}
        full.append({CODE: row[CODE], DATE: row[DATE], **prices, **execution,
                     TURNOVER: 0.0 if halted else row[TURNOVER], UPPER_LIMIT_HIT: False, LOWER_LIMIT_HIT: False,
                     QUALITY: "untradable" if halted else "ok", ADJUSTMENT_FACTOR: Decimal(1), EX_RIGHTS_TYPE: None})
    data = pd.DataFrame(full).set_index([CODE, DATE]).sort_index()
    return MarketFrame(data[COLUMNS])


def changed_after(rows: Sequence[dict], day: date, change: Callable[[dict], dict | None]) -> list[dict]:
    """`rows` with each row after `day` replaced by `change(row)`, or
    dropped where it gives None."""
    out = []
    for row in rows:
        if row[DATE] > day:
            row = change(dict(row))
            if row is None:
                continue
        out.append(row)
    return out
