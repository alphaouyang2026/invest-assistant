"""What every strategy shares (spec §6.2, A.3): the types on the seam, and
the wiring from a `MarketFrame` to each strategy's rules."""

from __future__ import annotations

import weakref
from collections.abc import Iterable, Mapping, Sequence
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


@dataclass(frozen=True)
class WarmupFollows:
    """How a strategy's warm-up follows one of its window parameters: it
    must be at least the parameter's value plus `extra` — the closes its
    rule reads, the day's own included. The new-account page sets the
    warm-up to that whenever the parameter changes."""

    parameter: str
    extra: int


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


def codes_to_read(strategy: Strategy, codes: Iterable[str]) -> list[str]:
    """What to read for `strategy` to judge `codes`: them and its reference
    series, each once — every caller reading bars for a strategy asks this,
    so none can leave the reference series out."""
    return sorted({*codes, *strategy.reference_series})


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
    `codes` order), with which codes can be judged on each session."""

    codes: list[str]
    rows: dict[date, int]
    judgeable: np.ndarray
    lines: dict[str, np.ndarray]


class _FrameStrategy:
    """What both kinds of strategy share: their lines worked out once per
    frame, and on the day each judgeable code judged on that day's readings.
    Subclasses work out a frame and judge a code."""

    name: str
    warmup_sessions: int
    plots: tuple[Plot, ...]
    universe_rule: UniverseRule
    reference_series: tuple[str, ...]
    warmup_follows: WarmupFollows | None = None  # a warm-up no single window decides

    def __init__(self, params: Mapping[str, Any]) -> None:
        self.params = params
        self._worked_out: weakref.WeakKeyDictionary[MarketFrame, _WorkedOut] = weakref.WeakKeyDictionary()

    def evaluate(self, frame: MarketFrame, day: date, holdings: Sequence[Holding]) -> list[Signal]:
        worked = self._worked_out_for(frame)
        at = worked.rows.get(day)
        if at is None:
            return []
        held = {holding.code: holding for holding in holdings}
        today = {name: values[at] for name, values in worked.lines.items()}

        signals = []
        for column in np.flatnonzero(worked.judgeable[at]):
            code = worked.codes[column]
            readings = {name: float(values[column]) for name, values in today.items()}
            judgement = self._judge_code(frame, day, readings, held.get(code))
            signals.append(Signal(code, judgement.disposition, judgement.reason_codes, readings, judgement.priority))
        return signals  # by code: the columns are

    def _worked_out_for(self, frame: MarketFrame) -> _WorkedOut:
        """Everything that depends on the frame alone, once per frame."""
        if frame not in self._worked_out:
            self._worked_out[frame] = self._work_out(frame)
        return self._worked_out[frame]

    def _work_out(self, frame: MarketFrame) -> _WorkedOut:
        raise NotImplementedError

    def _judge_code(self, frame: MarketFrame, day: date, readings: dict[str, float],
                    holding: Holding | None) -> Judgement:
        raise NotImplementedError


def _rows(index: pd.Index) -> dict[date, int]:
    return {day: n for n, day in enumerate(index)}


def _tradable(frame: MarketFrame, index: pd.Index, codes: Sequence[str]) -> np.ndarray:
    """Whether each code (a column) has a bar that is not untradable on each
    session (a row)."""
    quality = frame.wide(QUALITY).reindex(index=index, columns=codes)
    return (quality.notna() & (quality != UNTRADABLE)).to_numpy()


def whole_sessions(strategy: str, what: str, value: Any) -> int:
    """A window parameter as a count of sessions: refused unless a whole
    number of at least 1."""
    if not (isinstance(value, int | float) and value >= 1 and float(value).is_integer()):
        raise ValueError(f"{strategy} 的{what}要是至少 1 个开市日的整数，收到 {value}")
    return int(value)


class IndicatorStrategy(_FrameStrategy):
    """Works out a strategy's lines once per frame, then judges each code
    on the day from its readings. Subclasses give the lines and the rules."""

    universe_rule: UniverseRule = UniverseRule.PRIME_COMMON_STOCK
    reference_series: tuple[str, ...] = ()  # its lines come from each code's own bars

    def lines(self, bars: Bars) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    def judge(self, readings: dict[str, float], position: Position | None) -> Judgement:
        """May add what it works out along the way to `readings`."""
        raise NotImplementedError

    def _judge_code(self, frame: MarketFrame, day: date, readings: dict[str, float],
                    holding: Holding | None) -> Judgement:
        return self.judge(readings, self._position(frame, holding, day) if holding else None)

    def _work_out(self, frame: MarketFrame) -> _WorkedOut:
        """A code can be judged once it has had the warm-up's worth of bars
        and its bar that day is tradable."""
        bars = Bars(*(frame.wide(column).astype(float) for column in (OPEN, HIGH, LOW, CLOSE, VOLUME)))
        lines = self.lines(bars)
        index, codes = bars.close.index, bars.close.columns
        seen = bars.close.notna().cumsum().to_numpy()
        return _WorkedOut(
            codes=list(codes),
            rows=_rows(index),
            judgeable=(seen >= self.warmup_sessions) & _tradable(frame, index, codes),
            lines={name: line.reindex(index=index, columns=codes).to_numpy(float) for name, line in lines.items()},
        )

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


class ReferenceSeriesStrategy(_FrameStrategy):
    """Works out its lines from its reference series alone (CONTEXT.md
    参照行情), once per frame and a value per session, and judges every other
    code in the frame on them. A session can be judged once each reference
    series has a close that day and the warm-up's worth of closes behind it;
    then each other code with a bar that day that is not untradable gets a
    signal on the same readings, and a reference series never gets one.
    Subclasses give the lines and the rules — the TOPIX ETF strategies that
    follow TOPIX."""

    warmup_sessions: int  # closes of each reference series, the day's own included

    def lines(self, closes: pd.DataFrame) -> dict[str, pd.Series]:
        """`closes` are the reference series' research closes, a row per
        session of the frame and a column per code, NaN where one has none.
        Each line has a value per session."""
        raise NotImplementedError

    def judge_on_reference(self, readings: dict[str, float], held: bool) -> Judgement:
        """The rules, on the reference series' readings alone and whether the
        code is held. May add what it works out along the way to `readings`."""
        raise NotImplementedError

    def _judge_code(self, frame: MarketFrame, day: date, readings: dict[str, float],
                    holding: Holding | None) -> Judgement:
        return self.judge_on_reference(readings, holding is not None)

    def _work_out(self, frame: MarketFrame) -> _WorkedOut:
        closes = frame.wide(CLOSE).astype(float)
        reference = closes.reindex(columns=list(self.reference_series))
        present = reference.notna()
        others = [code for code in closes.columns if code not in self.reference_series]
        ready = (present & (present.cumsum() >= self.warmup_sessions)).all(axis=1).to_numpy()
        shape = (len(closes.index), len(others))
        return _WorkedOut(
            codes=others,
            rows=_rows(closes.index),
            judgeable=ready[:, None] & _tradable(frame, closes.index, others),
            # the same value for every code on a session
            lines={name: np.broadcast_to(line.reindex(closes.index).to_numpy(float)[:, None], shape)
                   for name, line in self.lines(reference).items()},
        )
