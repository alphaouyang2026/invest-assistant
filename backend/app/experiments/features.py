"""Features and labels for the first model experiment (ticket 06a): a
decision day `t` and a code make one sample.

The features are worked out from research prices up to `t`'s close alone,
counting over the bars the code has (spec §5: a halt is no bar), as
`Bars.back` does. They are all ratios: a split after `t` rescales the
research prices before it (CONTEXT.md 研究价格), so an absolute price or
volume would change after the fact. Turnover is yen, which no split moves,
so its level is a feature too. A row missing any feature is left out: it
neither trains a model nor gets a score.

The label is what a position bought at the next session's open would have
made by the open `horizon` sessions later — the earliest fill and the exit
the task freezes — counting sessions of the trading calendar (the frame's
dates), not the code's bars. With no open on either session (a halt, no
bar, past the frame) the sample has no label.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date

import numpy as np
import pandas as pd

from app.market_data import CLOSE, HIGH, LOW, OPEN, TURNOVER, VOLUME, MarketFrame
from app.market_data.frame import CODE, DATE

FEATURES_V1 = "ohlcv_ratios_v1"
FEATURE_NAMES = (
    "ret_1", "ret_5", "ret_20", "ret_60",   # close over the close that many bars back, less 1
    "dist_sma20", "dist_sma60",             # close over its moving average, less 1
    "vol_20",                               # standard deviation of the last 20 daily log returns
    "range_20",                             # mean (high − low) / close over the last 20 bars
    "volume_ratio",                         # mean volume of the last 5 bars over that of the last 20
    "log_turnover_20",                      # log of the mean turnover of the last 20 bars
)
AS_OF = "as_of"  # the decision day: its close is the last one a sample's features see
HORIZON = 5


def label_sessions(horizon: int = HORIZON) -> int:
    """How many sessions after its decision day a label ends: it runs from
    the next session's open to the open `horizon` sessions after that."""
    return horizon + 1


def feature_table(frame: MarketFrame, days: Sequence[date]) -> pd.DataFrame:
    """A row per code with every feature on each of `days`, indexed
    (as_of, code); a column per feature, in `FEATURE_NAMES` order."""
    data = frame.data.sort_index()
    bars = data[data[CLOSE].notna()]
    close, high, low = (bars[column].astype(float) for column in (CLOSE, HIGH, LOW))
    volume, turnover = bars[VOLUME].astype(float), bars[TURNOVER].astype(float)

    columns = {f"ret_{n}": close / _back(close, n) - 1 for n in (1, 5, 20, 60)}
    columns |= {f"dist_sma{n}": close / _mean(close, n) - 1 for n in (20, 60)}
    columns["vol_20"] = _std(np.log(close / _back(close, 1)), 20)
    columns["range_20"] = _mean((high - low) / close, 20)
    columns["volume_ratio"] = _mean(volume, 5) / _mean(volume, 20)
    with np.errstate(divide="ignore"):
        columns["log_turnover_20"] = np.log(_mean(turnover, 20))
    table = pd.DataFrame(columns)[list(FEATURE_NAMES)]

    table = table[table.index.get_level_values(DATE).isin(set(days))]
    table = table.replace([np.inf, -np.inf], np.nan).dropna()
    return _by_day(table)


def labels(frame: MarketFrame, days: Sequence[date], horizon: int = HORIZON) -> pd.Series:
    """The research open `horizon + 1` sessions after each of `days` over
    the one the session after it, less 1, indexed (as_of, code); only the
    samples that have one."""
    opens = frame.wide(OPEN).astype(float).sort_index()
    returns = opens.shift(-label_sessions(horizon)) / opens.shift(-1) - 1
    returns = returns[returns.index.isin(set(days))]
    stacked = returns.rename_axis(index=DATE, columns=CODE).stack().replace([np.inf, -np.inf], np.nan).dropna()
    return _by_day(stacked).rename("label")


def within_universe(table: pd.DataFrame | pd.Series,
                    universes: Mapping[date, Iterable[str]]) -> pd.DataFrame | pd.Series:
    """The rows of a table indexed (as_of, code) whose code is in its day's
    universe (CONTEXT.md 股票池) — the codes a model is trained on and
    scores; a day `universes` does not have keeps nothing."""
    pairs = [(day, code) for day, codes in universes.items() for code in codes]
    return table[table.index.isin(pairs)]


def _by_day(table: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Indexed (code, date) or (date, code) → (as_of, code), oldest day first."""
    swapped = table.swaplevel(CODE, DATE) if table.index.names[0] == CODE else table
    return swapped.rename_axis(index=[AS_OF, CODE]).sort_index()


def _back(line: pd.Series, bars: int) -> pd.Series:
    return line.groupby(level=CODE).shift(bars)


def _mean(line: pd.Series, bars: int) -> pd.Series:
    return line.groupby(level=CODE).rolling(bars, min_periods=bars).mean().droplevel(0)


def _std(line: pd.Series, bars: int) -> pd.Series:
    return line.groupby(level=CODE).rolling(bars, min_periods=bars).std().droplevel(0)
