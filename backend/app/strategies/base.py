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

from app.market_data import CLOSE, HIGH, LOW, OPEN, QUALITY, VOLUME, MarketFrame, UniverseRule

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
    # Where it opens positions (spec §6.1): callers ask the market data
    # module for this universe; the strategy judges whatever is in the frame.
    universe_rule: UniverseRule
    # Codes it reads but never trades (CONTEXT.md 参照行情) — TOPIX, say:
    # callers add them to what they read; `evaluate` takes them as input
    # only and never gives one of them a signal.
    reference_series: tuple[str, ...]

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


@dataclass(frozen=True)
class _WorkedOut:
    """A frame's lines as arrays (a row per session, a column per code, in
    `codes` order), with how many bars each code has had by each session and
    whether it is tradable that day."""

    codes: list[str]
    rows: dict[date, int]
    seen: np.ndarray
    tradable: np.ndarray
    lines: dict[str, np.ndarray]


class IndicatorStrategy:
    """Works out a strategy's lines once per frame, then judges each code
    on the day from its readings. Subclasses give the lines and the rules."""

    name: str
    warmup_sessions: int
    plots: tuple[Plot, ...]
    universe_rule: UniverseRule = UniverseRule.PRIME_COMMON_STOCK
    reference_series: tuple[str, ...] = ()  # its lines come from each code's own bars

    def __init__(self, params: Mapping[str, Any]) -> None:
        self.params = params
        self._worked_out: weakref.WeakKeyDictionary[MarketFrame, _WorkedOut] = weakref.WeakKeyDictionary()

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        """May add what it works out along the way to `readings`."""
        raise NotImplementedError

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]:
        worked = self._worked_out_for(frame)
        if day not in worked.rows:
            return []
        at = worked.rows[day]
        judgeable = (worked.seen[at] >= self.warmup_sessions) & worked.tradable[at]
        held = {holding.code: holding for holding in holdings}
        today = {name: values[at] for name, values in worked.lines.items()}

        signals = []
        for column in np.flatnonzero(judgeable):
            code = worked.codes[column]
            readings = {name: float(values[column]) for name, values in today.items()}
            position = self._position(frame, held[code], day) if code in held else None
            judgement = self.judge(readings, position)
            signals.append(Signal(code, judgement.disposition, judgement.reason_codes, readings, judgement.priority))
        return signals  # by code: the columns are

    def _worked_out_for(self, frame: MarketFrame) -> _WorkedOut:
        """Everything that depends on the frame alone, once per frame."""
        if frame not in self._worked_out:
            bars = Bars(*(frame.wide(column).astype(float) for column in (OPEN, HIGH, LOW, CLOSE, VOLUME)))
            lines = self.lines(bars)
            quality = frame.wide(QUALITY).reindex(index=bars.close.index, columns=bars.close.columns)
            self._worked_out[frame] = _WorkedOut(
                codes=list(bars.close.columns),
                rows={day: n for n, day in enumerate(bars.close.index)},
                seen=bars.close.notna().cumsum().to_numpy(),
                tradable=(quality.notna() & (quality != UNTRADABLE)).to_numpy(),
                lines={name: line.reindex(index=bars.close.index, columns=bars.close.columns).to_numpy(float)
                       for name, line in lines.items()},
            )
        return self._worked_out[frame]

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


@dataclass(frozen=True)
class _ReferenceWorkedOut:
    """A frame as a strategy on its reference series sees it: the lines (a
    value per session), the sessions they can be judged on, and which of the
    other codes (in `codes` order) are tradable on each."""

    codes: list[str]
    rows: dict[date, int]
    ready: np.ndarray
    tradable: np.ndarray
    lines: dict[str, np.ndarray]


class ReferenceSeriesStrategy:
    """Works out its lines from its reference series alone (CONTEXT.md
    参照行情), once per frame and a value per session, and judges every other
    code in the frame on them. A session can be judged once each reference
    series has a close that day and the warm-up's worth of closes behind it;
    then each other code with a bar that day that is not untradable gets a
    signal on the same readings, and a reference series never gets one.
    Subclasses give the lines and the rules — the TOPIX ETF strategies that
    follow TOPIX."""

    name: str
    warmup_sessions: int  # closes of each reference series, the day's own included
    plots: tuple[Plot, ...]
    universe_rule: UniverseRule
    reference_series: tuple[str, ...]

    def __init__(self, params: Mapping[str, Any]) -> None:
        self.params = params
        self._worked_out: weakref.WeakKeyDictionary[MarketFrame, _ReferenceWorkedOut] = weakref.WeakKeyDictionary()

    def lines(self, closes: pd.DataFrame) -> dict[str, pd.Series]:
        """`closes` are the reference series' research closes, a row per
        session of the frame and a column per code, NaN where one has none.
        Each line has a value per session."""
        raise NotImplementedError

    def judge(self, readings: dict[str, float], held: bool) -> Judgement:
        """May add what it works out along the way to `readings`."""
        raise NotImplementedError

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]:
        worked = self._worked_out_for(frame)
        at = worked.rows.get(day)
        if at is None or not worked.ready[at]:
            return []
        held = {holding.code for holding in holdings}
        today = {name: float(values[at]) for name, values in worked.lines.items()}

        signals = []
        for column in np.flatnonzero(worked.tradable[at]):
            code = worked.codes[column]
            readings = dict(today)
            judgement = self.judge(readings, code in held)
            signals.append(Signal(code, judgement.disposition, judgement.reason_codes, readings, judgement.priority))
        return signals  # by code: the columns are

    def _worked_out_for(self, frame: MarketFrame) -> _ReferenceWorkedOut:
        """Everything that depends on the frame alone, once per frame."""
        if frame not in self._worked_out:
            closes = frame.wide(CLOSE).astype(float)
            reference = closes.reindex(columns=list(self.reference_series))
            present = reference.notna()
            others = [code for code in closes.columns if code not in self.reference_series]
            quality = frame.wide(QUALITY).reindex(index=closes.index, columns=others)
            self._worked_out[frame] = _ReferenceWorkedOut(
                codes=others,
                rows={day: n for n, day in enumerate(closes.index)},
                ready=(present & (present.cumsum() >= self.warmup_sessions)).all(axis=1).to_numpy(),
                tradable=(quality.notna() & (quality != UNTRADABLE)).to_numpy(),
                lines={name: line.reindex(closes.index).to_numpy(float) for name, line in self.lines(reference).items()},
            )
        return self._worked_out[frame]
