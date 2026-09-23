"""The split check (spec §4.3, ADR-0003): does the local research close
agree with J-Quants' own adjusted close before an ex-rights day?

If a factor was stored wrong or missed, every research price before it is
off by that much; J-Quants' `AdjC` is the independent answer to compare
against.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal

from app.market_data.jquants import BarRecord

SESSIONS_BEFORE = 60
BACKFILL_SAMPLE = 20

# AdjC keeps one decimal, so 0.1 yen apart is rounding, not disagreement,
# however cheap the stock; 0.1 % covers the rounding of dearer ones. A
# difference has to clear both to count.
ABSOLUTE_TOLERANCE = Decimal("0.1")
RELATIVE_TOLERANCE = Decimal("0.001")


def research_closes(bars: Iterable[tuple[date, Decimal | None, Decimal]]) -> dict[date, Decimal]:
    """(date, execution close, adjustment factor) of one security, any
    order, through its latest stored date → research close per date, exact."""
    closes: dict[date, Decimal] = {}
    factor_after = Decimal(1)
    for day, close, factor in sorted(bars, reverse=True):
        if close is not None:
            closes[day] = close * factor_after
        factor_after *= factor
    return closes


def disagreements(local: Mapping[date, Decimal], jquants: Iterable[BarRecord]) -> list[tuple[date, Decimal, Decimal]]:
    """(date, local, J-Quants) for every date both know and disagree on."""
    found = []
    for record in jquants:
        ours, theirs = local.get(record.date), record.adjusted_close
        if ours is None or theirs is None:
            continue
        difference = abs(ours - theirs)
        if difference > ABSOLUTE_TOLERANCE and difference > RELATIVE_TOLERANCE * abs(theirs):
            found.append((record.date, ours, theirs))
    return sorted(found)


def warning_for(code: str, ex_date: date, found: list[tuple[date, Decimal, Decimal]]) -> str:
    day, ours, theirs = found[0]
    return (
        f"{code} 拆合股核对不符（除权日 {ex_date.isoformat()}）：{len(found)} 天对不上，"
        f"例如 {day.isoformat()} 本地研究收盘价 {ours:.2f}、J-Quants 复权收盘价 {theirs}"
    )
