"""Indicators (spec §5, indicators.md §2): pure functions, no database.

Each takes one security's `Series` or a wide `DataFrame` (rows are
sessions, columns are codes) and returns the same shape. The comment on
each names the Pine function it follows.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

Prices = pd.Series | pd.DataFrame


def sma(source: Prices, n: int) -> Prices:
    """`ta.sma`: the mean of the last `n` bars; NaN until there are `n`."""
    return _over_bars(lambda bars: bars.rolling(n).mean(), source)


def ema(source: Prices, n: int) -> Prices:
    """`ta.ema`, α = 2/(n+1). Seeded with the mean of the first `n` bars —
    what TradingView's built-in does, not the reference manual's example
    (indicators.md §5.1)."""
    return _over_bars(lambda bars: _seeded_smoothing(bars, n, 2 / (n + 1)), source)


def rma(source: Prices, n: int) -> Prices:
    """`ta.rma` (Wilder), α = 1/n, seeded with the mean of the first `n` bars."""
    return _over_bars(lambda bars: _seeded_smoothing(bars, n, 1 / n), source)


def rsi(source: Prices, n: int) -> Prices:
    """`ta.rsi`: Wilder-smoothed gains over Wilder-smoothed losses."""
    def over(bars: pd.Series) -> pd.Series:
        change = bars.diff()
        gains, losses = rma(change.clip(lower=0), n), rma((-change).clip(lower=0), n)
        # Pine checks losses first: none at all is 100 even with no gains.
        return (100 - 100 / (1 + gains / losses)).mask(losses == 0, 100.0)
    return _over_bars(over, source)


def atr(high: Prices, low: Prices, close: Prices, n: int) -> Prices:
    """`ta.atr`: the Wilder-smoothed true range."""
    return _over_bars(lambda h, l, c: rma(_true_range(h, l, c), n), high, low, close)


def dmi(high: Prices, low: Prices, close: Prices, di_length: int, adx_length: int):
    """`ta.dmi` → (+DI, −DI, ADX)."""
    def over(h: pd.Series, l: pd.Series, c: pd.Series):
        up, down = h.diff(), -l.diff()
        plus_dm = up.where((up > down) & (up > 0), 0.0).where(up.notna())
        minus_dm = down.where((down > up) & (down > 0), 0.0).where(down.notna())
        # `ta.tr` without its argument: no value on the first bar, unlike ATR's.
        true_range = rma(_true_range(h, l, c).where(c.shift(1).notna()), di_length)
        plus = 100 * rma(plus_dm, di_length) / true_range
        minus = 100 * rma(minus_dm, di_length) / true_range
        total = plus + minus
        adx = 100 * rma((plus - minus).abs() / total.mask(total == 0, 1.0), adx_length)
        return plus, minus, adx
    return _over_bars(over, high, low, close)


def hma(source: Prices, n: int) -> Prices:
    """`ta.hma`: WMA(2·WMA(x, n/2) − WMA(x, n), √n), both lengths rounded
    down — 4 and 3 for n = 9, matched against TradingView (indicators.md §5.5)."""
    def over(bars: pd.Series) -> pd.Series:
        return _wma(2 * _wma(bars, n // 2) - _wma(bars, n), math.isqrt(n))
    return _over_bars(over, source)


def vwma(close: Prices, volume: Prices, n: int) -> Prices:
    """`ta.vwma`: SMA(close·volume, n) / SMA(volume, n)."""
    def over(c: pd.Series, v: pd.Series) -> pd.Series:
        return (c * v).rolling(n).mean() / v.rolling(n).mean()
    return _over_bars(over, close, volume)


def ichimoku(high: Prices, low: Prices, conversion_length: int, base_length: int, span_b_length: int):
    """`ta.ichimoku` (TradingView/ta library) → (conversion, base, span A,
    span B), unshifted: span A and B are drawn 26 bars ahead, which the
    rating reads as their values 26 bars back."""
    def over(h: pd.Series, l: pd.Series):
        def midpoint(k: int) -> pd.Series:
            return (h.rolling(k).max() + l.rolling(k).min()) / 2
        conversion, base = midpoint(conversion_length), midpoint(base_length)
        return conversion, base, (conversion + base) / 2, midpoint(span_b_length)
    return _over_bars(over, high, low)


def stochastic(high: Prices, low: Prices, close: Prices, period_k: int, smooth_k: int, period_d: int):
    """`ta.stochFull` (TradingView/ta library) → (%K, %D)."""
    def over(h: pd.Series, l: pd.Series, c: pd.Series):
        k = _stoch(c, h, l, period_k).rolling(smooth_k).mean()
        return k, k.rolling(period_d).mean()
    return _over_bars(over, high, low, close)


def cci(source: Prices, n: int) -> Prices:
    """`ta.cci` on the close (the rating's input, indicators.md §5.9):
    (x − SMA) / (0.015 · mean absolute deviation); NaN when that is 0."""
    def over(bars: pd.Series) -> pd.Series:
        mean = bars.rolling(n).mean()
        deviation = sum((bars.shift(k) - mean).abs() for k in range(n)) / n
        return (bars - mean) / (0.015 * deviation.where(deviation != 0))
    return _over_bars(over, source)


def awesome_oscillator(high: Prices, low: Prices, short: int, long: int) -> Prices:
    """`ta.ao` (TradingView/ta library): SMA(hl2, short) − SMA(hl2, long)."""
    def over(h: pd.Series, l: pd.Series) -> pd.Series:
        midpoint = (h + l) / 2
        return midpoint.rolling(short).mean() - midpoint.rolling(long).mean()
    return _over_bars(over, high, low)


def momentum(source: Prices, n: int) -> Prices:
    """`ta.mom`: x − x[n]."""
    return _over_bars(lambda bars: bars.diff(n), source)


def macd(source: Prices, fast: int, slow: int, signal: int):
    """`ta.macd` → (MACD line, signal line); the signal EMA starts from its
    own first `signal` values."""
    def over(bars: pd.Series):
        line = ema(bars, fast) - ema(bars, slow)
        return line, ema(line, signal)
    return _over_bars(over, source)


def stoch_rsi(source: Prices, rsi_length: int, period_k: int, smooth_k: int, period_d: int):
    """`ta.stochRsi` (TradingView/ta library) → (K, D)."""
    def over(bars: pd.Series):
        strength = rsi(bars, rsi_length)
        k = _stoch(strength, strength, strength, period_k).rolling(smooth_k).mean()
        return k, k.rolling(period_d).mean()
    return _over_bars(over, source)


def williams_r(high: Prices, low: Prices, close: Prices, n: int) -> Prices:
    """`ta.wpr`: −100 … 0; NaN when the range is empty."""
    return _over_bars(lambda h, l, c: _stoch(c, h, l, n) - 100, high, low, close)


def bull_bear_power(high: Prices, low: Prices, close: Prices, n: int):
    """Bull and bear power as the rating library writes them → (high −
    EMA(close, n), low − EMA(close, n))."""
    def over(h: pd.Series, l: pd.Series, c: pd.Series):
        average = ema(c, n)
        return h - average, l - average
    return _over_bars(over, high, low, close)


def ultimate_oscillator(high: Prices, low: Prices, close: Prices, fast: int, middle: int, slow: int) -> Prices:
    """`ta.uo` (TradingView/ta library): 100·(4·A_fast + 2·A_middle + A_slow)/7,
    A = Σ buying pressure / Σ true range; NaN when a Σ true range is 0."""
    def over(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
        previous = c.shift(1)
        floor, ceiling = np.minimum(l, previous), np.maximum(h, previous)
        pressure, true_range = c - floor, ceiling - floor

        def average(k: int) -> pd.Series:
            ranges = true_range.rolling(k).sum()
            return pressure.rolling(k).sum() / ranges.where(ranges != 0)
        return 100 * (4 * average(fast) + 2 * average(middle) + average(slow)) / 7
    return _over_bars(over, high, low, close)


def _stoch(source: pd.Series, high: pd.Series, low: pd.Series, n: int) -> pd.Series:
    """`ta.stoch`: where `source` sits in the last `n` bars' range, 0–100;
    NaN when the range is empty."""
    highest, lowest = high.rolling(n).max(), low.rolling(n).min()
    spread = highest - lowest
    return 100 * (source - lowest) / spread.where(spread != 0)


def _wma(bars: pd.Series, n: int) -> pd.Series:
    """`ta.wma`: weights 1 … n, the newest bar weighing most."""
    return sum((n - k) * bars.shift(k) for k in range(n)) / (n * (n + 1) / 2)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """`ta.tr`; the first bar, with no previous close, is high − low."""
    previous = close.shift(1)
    return np.fmax(np.fmax(high - low, (high - previous).abs()), (low - previous).abs())


def _seeded_smoothing(bars: Prices, n: int, alpha: float) -> Prices:
    """x[t]·α + s[t−1]·(1 − α), starting at each column's `n`-th bar from
    the mean of its first `n`; NaN before that. Columns may start late."""
    count = bars.notna().cumsum()
    seed = bars.where(count <= n).sum() / n
    started = bars.where(count > n).mask(count.eq(n) & bars.notna(), seed, axis=_columns(bars))
    return started.ewm(alpha=alpha, adjust=False).mean()


def _columns(bars: Prices):
    return 1 if isinstance(bars, pd.DataFrame) else None


def _over_bars(compute, *sources: Prices):
    """NaN is a day without a bar (spec §5): `compute` sees only the bars
    there are — a day any source lacks is dropped from all of them — and
    the missing days come back as NaN. `compute` may return one series or
    a tuple of them, and must work on a frame as well as a series.

    Codes whose bars run unbroken (however late they start or early they
    stop) are worked out together in one frame; only codes with a halt in
    the middle go one by one."""
    first = sources[0]
    if not isinstance(first, pd.DataFrame):
        present = pd.concat(sources, axis=1).notna().all(axis=1)
        result = compute(*(source[present] for source in sources))
        return _each(result, lambda part: part.reindex(first.index))

    present = pd.concat(sources, keys=range(len(sources))).notna().groupby(level=1).all().reindex(first.index)
    started, still_going = present.cummax(), present[::-1].cummax()[::-1]
    unbroken = ~(started & still_going & ~present).any()
    together = list(first.columns[unbroken])
    alone = list(first.columns[~unbroken])

    parts = []
    if together:
        result = compute(*(source[together].where(present[together]) for source in sources))
        parts.append(_each(result, lambda part: part.where(present[together])))
    if alone:
        by_code = {code: _over_bars(compute, *(source[code] for source in sources)) for code in alone}
        parts.append(_each_code(by_code, first.index))
    return _joined(parts, list(first.columns))


def _each(result, apply):
    return tuple(apply(part) for part in result) if isinstance(result, tuple) else apply(result)


def _each_code(by_code: dict, index: pd.Index):
    sample = next(iter(by_code.values()))
    if isinstance(sample, tuple):
        return tuple(pd.DataFrame({code: result[i] for code, result in by_code.items()}, index=index)
                     for i in range(len(sample)))
    return pd.DataFrame(by_code, index=index)


def _joined(parts: list, columns: list):
    if isinstance(parts[0], tuple):
        return tuple(pd.concat([part[i] for part in parts], axis=1)[columns] for i in range(len(parts[0])))
    return pd.concat(parts, axis=1)[columns]
