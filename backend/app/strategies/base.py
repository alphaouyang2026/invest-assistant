"""What every strategy shares (spec §6.2, A.3): the types on the seam, and
the wiring from a `MarketFrame` to each strategy's rules."""

from __future__ import annotations

import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Literal, Protocol

import numpy as np
import pandas as pd

from app.market_data import CLOSE, HIGH, LOW, OPEN, QUALITY, VOLUME, MarketFrame

UNTRADABLE = "untradable"


class Disposition(Enum):
    """A signal's value (CONTEXT.md 处置): an intent, not a trade."""

    HOLD = "hold"          # 可持有
    EXIT = "exit"          # 必须清仓
    STAY_OUT = "stay_out"  # 不参与


@dataclass(frozen=True)
class Judgement:
    """What a strategy's rules make of one security on one session."""

    disposition: Disposition
    reason_codes: tuple[str, ...] = ()
    priority: float | None = None  # entry candidates only; higher first


@dataclass(frozen=True)
class Holding:
    code: str
    quantity: int
    opened_on: date  # the session its first shares were bought


@dataclass(frozen=True)
class Signal:
    code: str
    disposition: Disposition
    reason_codes: tuple[str, ...]
    indicators: Mapping[str, float]  # the readings the rules saw that day
    priority: float | None


@dataclass(frozen=True)
class Plot:
    indicator: str
    pane: Literal["price", "separate"]


@dataclass(frozen=True)
class Position:
    """A holding's facts as the strategy works them out from the bars."""

    sessions_held: int     # bars from the opening session to the day, both counted
    highest_close: float   # the highest research close over those bars


class Strategy(Protocol):
    name: str
    warmup_sessions: int
    plots: tuple[Plot, ...]

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]: ...


@dataclass(frozen=True)
class Bars:
    """A frame's research prices as wide tables, for working out lines."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame

    def back(self, line: pd.DataFrame, sessions: int) -> pd.DataFrame:
        """`line` as it was `sessions` bars earlier — Pine's `line[k]` —
        counting only days the code has a bar (spec §5: a halt is no bar)."""
        present = self.close.notna()
        started, going_on = present.cummax(), present[::-1].cummax()[::-1]
        broken = (started & going_on & ~present).any()
        shifted = line.shift(sessions).where(present)
        for code in present.columns[broken]:
            bars = present[code]
            shifted[code] = line[code][bars].shift(sessions).reindex(line.index)
        return shifted


class IndicatorStrategy:
    """Works out a strategy's lines once per frame, then judges each code
    on the day from its readings. Subclasses give the lines and the rules."""

    name: str
    warmup_sessions: int
    plots: tuple[Plot, ...]

    def __init__(self, params: Mapping[str, Any]) -> None:
        self.params = params
        self._lines_by_frame: weakref.WeakKeyDictionary[MarketFrame, dict[str, pd.DataFrame]] = (
            weakref.WeakKeyDictionary()
        )

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        """May add what it works out along the way to `readings`."""
        raise NotImplementedError

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]:
        lines = self._lines_for(frame)
        quality = frame.wide(QUALITY)
        if day not in quality.index:
            return []
        seen = frame.wide(CLOSE).notna().loc[:day].sum()
        judgeable = (seen >= self.warmup_sessions) & (quality.loc[day] != UNTRADABLE) & quality.loc[day].notna()
        held = {holding.code: holding for holding in holdings}
        row = {name: line.loc[day] for name, line in lines.items()}

        signals = []
        for code in quality.columns[judgeable]:
            readings = {name: float(values[code]) for name, values in row.items()}
            position = self._position(frame, held[code], day) if code in held else None
            judgement = self.judge(readings, position)
            signals.append(Signal(code, judgement.disposition, judgement.reason_codes, readings, judgement.priority))
        return sorted(signals, key=lambda signal: signal.code)

    def _lines_for(self, frame: MarketFrame) -> dict[str, pd.DataFrame]:
        if frame not in self._lines_by_frame:
            bars = Bars(*(frame.wide(column).astype(float) for column in (OPEN, HIGH, LOW, CLOSE, VOLUME)))
            self._lines_by_frame[frame] = self.lines(bars)
        return self._lines_by_frame[frame]

    @staticmethod
    def _position(frame: MarketFrame, holding: Holding, day: date) -> Position:
        bars = frame.data.xs(holding.code, level="code")
        first = bars.index.min()
        if first > holding.opened_on:
            raise ValueError(
                f"{holding.code} 的行情从 {first} 才开始，晚于开仓日 {holding.opened_on}：开仓以来最高收盘价会算低"
            )
        since = bars.loc[holding.opened_on:day]
        return Position(sessions_held=len(since), highest_close=float(np.nanmax(since[CLOSE].to_numpy(float))))
