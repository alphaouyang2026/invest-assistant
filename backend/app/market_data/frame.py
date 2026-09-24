"""`MarketFrame` — what `MarketData.read` hands back.

A thin wrapper over one DataFrame indexed by (code, date), oldest first
within each code. The column names below are part of the interface;
callers use the constants, not string literals.

Research prices (`OPEN` … `VOLUME`) are floats, adjusted by every later
adjustment factor the database holds (spec §4.3) — for indicators and
signals. Execution prices (`EXEC_*`) are the day's actual `Decimal`
prices — for fills and bookkeeping. Where J-Quants had no price (a halt),
research columns are NaN and execution columns are None.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

import pandas as pd

CODE = "code"
DATE = "date"

OPEN = "open"
HIGH = "high"
LOW = "low"
CLOSE = "close"
VOLUME = "volume"

EXEC_OPEN = "exec_open"
EXEC_HIGH = "exec_high"
EXEC_LOW = "exec_low"
EXEC_CLOSE = "exec_close"

TURNOVER = "turnover"  # yen, float: it feeds thresholds, not the books
UPPER_LIMIT_HIT = "upper_limit_hit"
LOWER_LIMIT_HIT = "lower_limit_hit"
QUALITY = "quality_status"  # "ok" / "excluded" / "untradable" (spec §4.4)

COLUMNS = [
    OPEN, HIGH, LOW, CLOSE, VOLUME,
    EXEC_OPEN, EXEC_HIGH, EXEC_LOW, EXEC_CLOSE,
    TURNOVER, UPPER_LIMIT_HIT, LOWER_LIMIT_HIT, QUALITY,
]

_PRICES = [("open", OPEN, EXEC_OPEN), ("high", HIGH, EXEC_HIGH), ("low", LOW, EXEC_LOW), ("close", CLOSE, EXEC_CLOSE)]
_SPLIT_TYPES = (1, 2)  # ExRT split and reverse split; 3 (rights issue) leaves volume alone


class MarketFrame:
    def __init__(self, data: pd.DataFrame) -> None:
        self.data = data

    def dates(self, code: str) -> list[date]:
        """The dates `code` has a bar on, oldest first."""
        if code not in self.data.index.get_level_values(CODE):
            return []
        return list(self.data.xs(code, level=CODE).index)

    def wide(self, column: str) -> pd.DataFrame:
        """`column` with a row per date and a column per code; NaN where a
        code has no bar that day — the shape the indicator module takes."""
        return self.data[column].unstack(CODE)


def build_frame(
    rows: Iterable[Mapping[str, Any]],
    later_factors: Iterable[Mapping[str, Any]],
) -> MarketFrame:
    """`rows` are the stored bars in the requested range; `later_factors`
    are the ex-rights days after it, which still adjust everything before
    them."""
    bars = pd.DataFrame([dict(row) for row in rows])
    if bars.empty:
        empty = pd.MultiIndex.from_arrays([[], []], names=[CODE, DATE])
        return MarketFrame(pd.DataFrame(columns=COLUMNS, index=empty))

    later = pd.DataFrame([dict(row) for row in later_factors], columns=[CODE, DATE, "adjustment_factor", "ex_rights_type"])
    everything = pd.concat([bars.assign(_in_range=True), later.assign(_in_range=False)], ignore_index=True)
    everything = everything.sort_values([CODE, DATE], ignore_index=True)

    factor = everything["adjustment_factor"].astype(float)
    volume_factor = factor.where(everything["ex_rights_type"].isin(_SPLIT_TYPES), 1.0)
    # Product of the factors strictly after each row: the running product
    # from the newest row back, less the row's own factor.
    price_after = _product_from_the_end(factor, everything[CODE]) / factor
    volume_after = _product_from_the_end(volume_factor, everything[CODE]) / volume_factor

    in_range = everything["_in_range"].astype(bool)
    stored = everything[in_range]
    out = pd.DataFrame(index=pd.MultiIndex.from_frame(stored[[CODE, DATE]]))
    for stored_name, research, execution in _PRICES:
        executed = stored[stored_name]
        out[research] = (executed.astype(float) * price_after[in_range]).to_numpy()
        out[execution] = executed.to_numpy()
    out[VOLUME] = (stored["volume"].astype(float) / volume_after[in_range]).to_numpy()
    out[TURNOVER] = stored["turnover"].astype(float).to_numpy()
    out[UPPER_LIMIT_HIT] = stored["upper_limit_hit"].astype(bool).to_numpy()
    out[LOWER_LIMIT_HIT] = stored["lower_limit_hit"].astype(bool).to_numpy()
    out[QUALITY] = stored["quality_status"].to_numpy()
    return MarketFrame(out[COLUMNS])


def _product_from_the_end(values: pd.Series, codes: pd.Series) -> pd.Series:
    return values[::-1].groupby(codes[::-1]).cumprod()[::-1]
