"""Segment periods: comparing a day's roster with what is still running.

Pure — no database. The sync hands in the segments still open, every code
ever seen, and the day's roster, and writes back what comes out.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date

from app.market_data.jquants import RosterEntry


@dataclass(frozen=True)
class OpenSegment:
    """A segment period still running (`valid_to` is NULL)."""

    code: str
    valid_from: date
    market_code: str
    product_category: str
    sector33: str


@dataclass
class SegmentChanges:
    # (code, valid_from, valid_to) of each segment to close
    closed: list[tuple[str, date, date]] = field(default_factory=list)
    opened: list[OpenSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def compare_roster(
    open_segments: Iterable[OpenSegment],
    known_codes: Collection[str],
    roster: Iterable[RosterEntry],
    *,
    day: date,
    previous_session: date | None,
) -> SegmentChanges:
    """Any change of market, product category or 33-sector closes the old
    segment on the previous session and opens a new one on `day`; leaving
    the roster closes it and opens nothing. Name and scale are not part of
    a segment."""
    running = {segment.code: segment for segment in open_segments}
    changes = SegmentChanges()
    listed_today: set[str] = set()

    for entry in sorted(roster, key=lambda entry: entry.code):
        listed_today.add(entry.code)
        today = OpenSegment(entry.code, day, entry.market_code, entry.product_category, entry.sector33)
        current = running.get(entry.code)
        if current is None:
            if entry.code in known_codes:
                changes.warnings.append(
                    f"{entry.code} 代码重新出现（{day.isoformat()}）：此前已从名册消失，按新区间记录"
                )
            changes.opened.append(today)
        elif _classification(current) != _classification(today):
            changes.closed.append((current.code, current.valid_from, previous_session))
            changes.opened.append(today)

    for code in sorted(running.keys() - listed_today):
        changes.closed.append((code, running[code].valid_from, previous_session))
    return changes


def _classification(segment: OpenSegment) -> tuple[str, str, str]:
    return segment.market_code, segment.product_category, segment.sector33
