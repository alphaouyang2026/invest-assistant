"""TOPIX market regimes and the intervals they form (issue 04b-B; rule basis
`.scratch/market-regime-backtesting-research.md` §3–5).

Pure functions over the caller's open sessions and TOPIX closes: no
database, no strategy, no orders. Every window is counted in positions of
`sessions`, so days the market is shut are never in one and never cut an
interval, while an open session without a usable close is a gap that makes
each window holding it unknown. A label for day t reads closes up to t only.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Context, Decimal, localcontext
from typing import Any, Literal

DEFINITION_VERSION = "topix_trend_vol_v1"

Trend = Literal["up", "down", "neutral", "unknown"]
Vol = Literal["high", "low", "unknown"]
Why = Literal["warmup", "gap"]  # why a dimension is unknown

TRENDS = ("up", "down", "neutral")
VOLS = ("high", "low")


@dataclass(frozen=True)
class Definition:
    """Frozen engineering defaults, not user-editable: a change is a new version."""
    version: str = DEFINITION_VERSION
    index: str = "TOPIX"
    field: str = "close"
    ma_sessions: int = 200
    slope_sessions: int = 20
    gap_threshold: Decimal = Decimal("0.01")
    rv_sessions: int = 20
    annualisation: int = 252
    rv_history: int = 252
    short_sessions: int = 20   # display flag only, never filters
    trend_min_closes: int = 220
    full_min_closes: int = 273

    def __post_init__(self) -> None:
        if self.trend_min_closes != self.ma_sessions + self.slope_sessions:
            raise ValueError("trend_min_closes must be ma_sessions + slope_sessions")
        if self.full_min_closes != self.rv_sessions + 1 + self.rv_history:
            raise ValueError("full_min_closes must be rv_sessions + 1 + rv_history")

    def rules(self) -> dict[str, Any]:
        """The version and the numbers, JSON-ready: all that decides a label."""
        rules: dict[str, Any] = asdict(self)
        rules["gap_threshold"] = str(self.gap_threshold)
        return rules

    def as_dict(self) -> dict[str, Any]:
        """The rules, with the formulas spelled out for the page."""
        shown = self.rules()
        percent = format((self.gap_threshold * 100).normalize(), "f")
        ma = f"MA{self.ma_sessions}"
        rv = f"RV{self.rv_sessions}"
        shown["formulas"] = {
            "ma200": f"{ma} = 含当日在内最近 {self.ma_sessions} 个开市日的 {self.index} 收盘价平均",
            "gap": f"偏离 = 当日收盘 ÷ {ma} − 1",
            "slope20": f"斜率 = 当日 {ma} ÷ {self.slope_sessions} 个开市日前的 {ma} − 1",
            "trend": f"上涨：偏离 > {percent}% 且斜率 > 0；下跌：偏离 < −{percent}% 且斜率 < 0；"
                     "其余为中性（震荡候选，不代表已确认横盘）",
            "rv20": f"{rv} = 最近 {self.rv_sessions} 个日收益（取对数）的样本标准差 × √{self.annualisation}",
            "rv_threshold": f"波动阈值 = 当日之前 {self.rv_history} 个 {rv} 的中位数，不含当日",
            "vol": f"{rv} 高于阈值为高波动，其余为低波动",
            "unknown": f"趋势至少要 {self.trend_min_closes} 个收盘，波动至少要 {self.full_min_closes} 个；"
                       "不够（预热不足）或其中有缺失、非正的收盘（数据缺口）时记为未知，不补值",
        }
        return shown


DEFINITION = Definition()


@dataclass(frozen=True)
class DayLabel:
    day: date
    close: Decimal | None          # None = missing or <= 0 (a gap)
    trend: Trend
    trend_unknown: Why | None
    vol: Vol
    vol_unknown: Why | None
    # Filled whenever their own window is complete, even while the label is
    # still unknown (MA200 comes 20 sessions before its slope).
    ma200: Decimal | None
    gap: Decimal | None
    slope20: Decimal | None
    rv20: float | None
    rv_threshold: float | None     # the median of the previous RV20s


@dataclass(frozen=True)
class RegimeFilter:
    trend: Literal["up", "down", "neutral"]
    volatility: Literal["high", "low"] | None = None  # None = trend only

    def __post_init__(self) -> None:
        if self.trend not in TRENDS:
            raise ValueError(f"没有这种趋势：{self.trend}")
        if self.volatility is not None and self.volatility not in VOLS:
            raise ValueError(f"没有这种波动水平：{self.volatility}")

    def matches(self, label: DayLabel) -> bool:
        """An unknown required dimension never matches; trend only ignores volatility."""
        return label.trend == self.trend and (self.volatility is None or label.vol == self.volatility)


@dataclass(frozen=True)
class RegimeInterval:
    start: date
    end: date
    sessions: int
    topix_start: Decimal
    topix_end: Decimal
    topix_return: float            # start close to end close; a single day is 0.0
    rv20_min: float | None
    rv20_max: float | None
    single_day: bool               # sessions == 1
    short: bool                    # sessions < short_sessions
    truncated_start: bool          # starts on the first search session, and the session before it matches too
    at_search_end: bool            # ends on the last search session; what follows is not looked at


@dataclass(frozen=True)
class Diagnostics:
    search_sessions: int
    matched_sessions: int
    warmup_unknown: list[tuple[date, date]]  # runs of search sessions a required dimension is still warming up
    gap_unknown: list[tuple[date, date]]     # … unknown because its window holds a gap
    gaps: list[date]                         # sessions in scope with a missing or non-positive close
    trend_counts: dict[str, int]             # over the search sessions
    vol_counts: dict[str, int]


@dataclass(frozen=True)
class Discovery:
    definition: dict[str, Any]
    filter: RegimeFilter
    search_from: date
    search_to: date
    labels: list[DayLabel]         # search sessions only
    intervals: list[RegimeInterval]    # oldest first; empty = nothing matched
    diagnostics: Diagnostics


def lookback_start(sessions: Sequence[date], search_from: date, d: Definition = DEFINITION) -> date:
    """The first session a discovery reads: enough for full labels on the
    first search session *and* the one before it (so a run already going
    when the search starts can be flagged)."""
    first = _first_at_or_after(sessions, search_from)
    return sessions[max(0, first - d.full_min_closes)]


def classify(sessions: Sequence[date], closes: Mapping[date, Decimal | float | None],
             d: Definition = DEFINITION) -> list[DayLabel]:
    """One label per session, oldest first."""
    _check_order(sessions)
    c = [_usable(closes.get(day)) for day in sessions]
    # bad[k] = how many unusable closes come before position k
    bad = [0]
    for value in c:
        bad.append(bad[-1] + (value is None))

    def unknown(i: int, length: int) -> Why | None:
        lo = i - length + 1
        if bad[i + 1] - bad[max(0, lo)]:
            return "gap"
        return "warmup" if lo < 0 else None

    def complete(i: int, length: int) -> bool:
        return unknown(i, length) is None

    labels = []
    with localcontext(Context(prec=28)):
        ma: list[Decimal | None] = [
            sum(c[i - d.ma_sessions + 1:i + 1], Decimal(0)) / d.ma_sessions  # type: ignore[arg-type]
            if complete(i, d.ma_sessions) else None
            for i in range(len(c))]
        r: list[float | None] = [
            math.log(c[j] / c[j - 1]) if complete(j, 2) else None  # type: ignore[operator]
            for j in range(len(c))]
        rv: list[float | None] = [
            statistics.stdev(r[i - d.rv_sessions + 1:i + 1]) * math.sqrt(d.annualisation)  # type: ignore[arg-type]
            if complete(i, d.rv_sessions + 1) else None
            for i in range(len(c))]

        for i, day in enumerate(sessions):
            close, mean = c[i], ma[i]
            gap = close / mean - 1 if close is not None and mean is not None else None
            before = ma[i - d.slope_sessions] if i >= d.slope_sessions else None
            slope = mean / before - 1 if mean is not None and before is not None else None
            trend_why = unknown(i, d.trend_min_closes)
            trend: Trend = "unknown"
            if trend_why is None:
                assert gap is not None and slope is not None
                if gap > d.gap_threshold and slope > 0:
                    trend = "up"
                elif gap < -d.gap_threshold and slope < 0:
                    trend = "down"
                else:
                    trend = "neutral"

            history = rv[i - d.rv_history:i] if i >= d.rv_history else []
            threshold = statistics.median(history) if history and None not in history else None  # type: ignore[type-var]
            vol_why = unknown(i, d.full_min_closes)
            vol: Vol = "unknown"
            if vol_why is None:
                assert rv[i] is not None and threshold is not None
                vol = "high" if rv[i] > threshold else "low"

            labels.append(DayLabel(day=day, close=close, trend=trend, trend_unknown=trend_why, vol=vol,
                                   vol_unknown=vol_why, ma200=mean, gap=gap, slope20=slope, rv20=rv[i],
                                   rv_threshold=threshold))
    return labels


def discover(sessions: Sequence[date], closes: Mapping[date, Decimal | float | None], search_from: date,
             search_to: date, filter: RegimeFilter, d: Definition = DEFINITION) -> Discovery:
    """Every maximal run of consecutive search sessions that matches `filter`.

    Reads the sessions from `lookback_start` through `search_to` and nothing
    after; runs are neither merged across a non-matching session nor
    dropped for being short."""
    if search_from > search_to:
        raise ValueError("搜索起点晚于终点")
    _check_order(sessions)
    first = _first_at_or_after(sessions, search_from)
    if sessions[first] > search_to:
        raise ValueError("搜索范围内没有开市日")
    begin = sessions.index(lookback_start(sessions, search_from, d))
    scope = [day for day in sessions[begin:] if day <= search_to]
    labels = classify(scope, closes, d)
    offset = first - begin
    searched = labels[offset:]

    runs: list[list[int]] = []
    for k, label in enumerate(searched):
        if not filter.matches(label):
            continue
        if runs and runs[-1][-1] == k - 1:
            runs[-1].append(k)
        else:
            runs.append([k])

    def interval(run: list[int]) -> RegimeInterval:
        days = [searched[k] for k in run]
        start, end = days[0], days[-1]
        assert start.close is not None and end.close is not None
        spread = [label.rv20 for label in days if label.rv20 is not None]
        previous = labels[offset - 1] if offset > 0 else None
        return RegimeInterval(
            start=start.day, end=end.day, sessions=len(days),
            topix_start=start.close, topix_end=end.close, topix_return=float(end.close / start.close - 1),
            rv20_min=min(spread) if spread else None, rv20_max=max(spread) if spread else None,
            single_day=len(days) == 1, short=len(days) < d.short_sessions,
            truncated_start=run[0] == 0 and previous is not None and filter.matches(previous),
            at_search_end=run[-1] == len(searched) - 1,
        )

    intervals = [interval(run) for run in runs]
    diagnostics = Diagnostics(
        search_sessions=len(searched),
        matched_sessions=sum(i.sessions for i in intervals),
        warmup_unknown=_spans(searched, lambda label: _why(label, filter) == "warmup"),
        gap_unknown=_spans(searched, lambda label: _why(label, filter) == "gap"),
        gaps=[label.day for label in labels if label.close is None],
        trend_counts={key: sum(label.trend == key for label in searched) for key in (*TRENDS, "unknown")},
        vol_counts={key: sum(label.vol == key for label in searched) for key in (*VOLS, "unknown")},
    )
    return Discovery(definition=d.as_dict(), filter=filter, search_from=search_from, search_to=search_to,
                     labels=searched, intervals=intervals, diagnostics=diagnostics)


def fingerprint(sessions: Sequence[date], closes: Mapping[date, Decimal | float | None],
                d: Definition = DEFINITION) -> dict[str, Any]:
    """What a discovery was worked out from — the definition's rules plus each
    session's close — so running it later can tell whether TOPIX changed.
    Sessions the caller leaves out (those after the search end) never
    count, and a close hashes the same whether it came as float or Decimal."""
    if not sessions:
        raise ValueError("没有开市日可以记录")
    _check_order(sessions)
    rows = [[day.isoformat(), _text(closes.get(day))] for day in sessions]
    # The rules, not their wording: rephrasing a formula for the page leaves every discovery valid.
    body = json.dumps({"definition": d.rules(), "closes": rows}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return {"sha256": hashlib.sha256(body.encode()).hexdigest(), "definition_version": d.version,
            "from": sessions[0].isoformat(), "through": sessions[-1].isoformat(), "sessions": len(sessions)}


def _why(label: DayLabel, filter: RegimeFilter) -> Why | None:
    """Why a search session cannot match, as far as the required dimensions go; a gap outranks warm-up."""
    reasons = [label.trend_unknown]
    if filter.volatility is not None:
        reasons.append(label.vol_unknown)
    if "gap" in reasons:
        return "gap"
    return "warmup" if "warmup" in reasons else None


def _spans(labels: Sequence[DayLabel], chosen: Callable[[DayLabel], bool]) -> list[tuple[date, date]]:
    spans: list[tuple[date, date]] = []
    previous = False
    for label in labels:
        now = chosen(label)
        if now and previous:
            spans[-1] = (spans[-1][0], label.day)
        elif now:
            spans.append((label.day, label.day))
        previous = now
    return spans


def _as_decimal(value: Decimal | float | int) -> Decimal:
    # repr keeps a float's shortest spelling: 2345.67, not its binary expansion
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def _usable(value: Decimal | float | None) -> Decimal | None:
    """A close counts only if present, finite and above zero; nothing is filled in."""
    if value is None:
        return None
    number = _as_decimal(value)
    return number if number.is_finite() and number > 0 else None


def _text(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    number = _as_decimal(value)
    return format(number.normalize(), "f") if number.is_finite() else str(number)


def _check_order(sessions: Sequence[date]) -> None:
    if any(a >= b for a, b in zip(sessions, sessions[1:])):
        raise ValueError("开市日必须按日期先后排列且不重复")


def _first_at_or_after(sessions: Sequence[date], day: date) -> int:
    for i, session in enumerate(sessions):
        if session >= day:
            return i
    raise ValueError("搜索范围内没有开市日")
