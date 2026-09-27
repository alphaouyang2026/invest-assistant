"""`Ledger` (spec §3.6, A.4): holdings, cash and pending orders worked out
from an account's records — never stored, and worked out here only, so
`advance` and `report` cannot come to disagree."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.accounts.records import BUY, FILLED, PENDING, SPLIT_ADJUSTMENT, Record
from app.accounts.statistics import ClosedPosition


@dataclass(frozen=True)
class Position:
    code: str
    quantity: int
    opened_on: date  # the session the shares went from none to some
    cost: Decimal    # what those shares cost, fees included


class Ledger:
    def __init__(self, initial_cash: Decimal, records: Iterable[Record] = ()) -> None:
        self.initial_cash = initial_cash
        self.records: tuple[Record, ...] = tuple(records)
        book = _Book(initial_cash)
        for record in _in_order(self.records):
            book.enter(record)
        self.cash = book.cash
        self.positions = dict(book.held)
        self.closed: list[ClosedPosition] = book.closed
        self.pending = [record for record in self.records if record.status == PENDING]

    def apply(self, records: Iterable[Record]) -> Ledger:
        """The ledger after `records`: new ones added, ones with a known id
        replacing what they were."""
        records = list(records)
        changed = {record.id: record for record in records if record.id is not None}
        kept = [changed.pop(record.id, record) if record.id is not None else record for record in self.records]
        added = [record for record in records if record.id is None or record.id in changed]
        return Ledger(self.initial_cash, [*kept, *added])

    def by_session(self, sessions: Sequence[date]) -> Iterator[tuple[date, Decimal, dict[str, Position]]]:
        """Cash and holdings at each session's close, in one pass."""
        book, ordered, next_record = _Book(self.initial_cash), _in_order(self.records), 0
        for day in sessions:
            while next_record < len(ordered) and ordered[next_record].execution_date <= day:
                book.enter(ordered[next_record])
                next_record += 1
            yield day, book.cash, dict(book.held)


class _Book:
    """Running cash and holdings, entered a record at a time; keeps each
    position that closes, with what it made."""

    def __init__(self, cash: Decimal) -> None:
        self.cash = cash
        self.held: dict[str, Position] = {}
        self.closed: list[ClosedPosition] = []
        self._spent: dict[str, Decimal] = {}
        self._got: dict[str, Decimal] = {}

    def enter(self, record: Record) -> None:
        self.cash += record.cash_delta
        if record.status != FILLED:
            return
        code, current = record.code, self.held.get(record.code)
        if record.kind == BUY:
            paid = -record.cash_delta
            self._spent[code] = self._spent.get(code, Decimal(0)) + paid
            self.held[code] = (
                Position(code, record.filled_quantity, record.execution_date, paid) if current is None
                else Position(code, current.quantity + record.filled_quantity, current.opened_on, current.cost + paid)
            )
            return
        if current is None:
            return
        self._got[code] = self._got.get(code, Decimal(0)) + record.cash_delta
        change = record.filled_quantity if record.kind == SPLIT_ADJUSTMENT else -record.filled_quantity
        remaining = current.quantity + change
        if remaining <= 0:
            del self.held[code]
            profit = self._got.pop(code, Decimal(0)) - self._spent.pop(code, Decimal(0))
            self.closed.append(ClosedPosition(code, current.opened_on, record.execution_date, profit))
        elif record.kind == SPLIT_ADJUSTMENT:
            self.held[code] = Position(code, remaining, current.opened_on, current.cost)
        else:
            share = Decimal(remaining) / Decimal(current.quantity)
            self.held[code] = Position(code, remaining, current.opened_on, current.cost * share)


def _in_order(records: Iterable[Record]) -> list[Record]:
    """By the session they take effect, then as they were written."""
    return sorted(records, key=lambda r: (r.execution_date, r.id is None, r.id or 0))

