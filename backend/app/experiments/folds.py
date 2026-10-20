"""Date folds for a model experiment (ticket 06a): the test span cut into
stretches of sessions end to end, each with the training window just
before it, and which decision days may train each fold's model.

The split is by session, so every code of a day lands in the same fold. A
fold's training cutoff is the session before its test stretch: its model
may use what was known at that close and nothing later. A sample's label
is known only on its last session, so a decision day trains the fold only
once that session is no later than the cutoff; the days just before the
cutoff, whose labels run into the test stretch, are left out.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Fold:
    number: int        # 1..N, oldest first
    train_from: date
    train_to: date     # the training cutoff: only what was known at this close
    test_from: date    # the session after train_to
    test_to: date


def make_folds(sessions: Sequence[date], *, test_from: date, test_to: date,
               train_sessions: int, test_sessions: int, expanding: bool = False) -> list[Fold]:
    """The sessions from `test_from` to `test_to` cut into test stretches of
    `test_sessions` sessions each, end to end (the last may be shorter),
    oldest first. Each trains on the `train_sessions` sessions before its
    stretch, or with `expanding` on every session from the first one in
    `sessions` — at least `train_sessions` of them either way. `sessions`
    is the trading calendar; the dates need not be sessions themselves."""
    if train_sessions < 1 or test_sessions < 1:
        raise ValueError(f"训练窗和测试段都要至少 1 个开市日，收到训练窗 {train_sessions}、测试段 {test_sessions}")
    if test_from > test_to:
        raise ValueError(f"测试起点 {test_from} 晚于测试终点 {test_to}")
    calendar = sorted(set(sessions))
    first, end = bisect_left(calendar, test_from), bisect_right(calendar, test_to)
    if first >= end:
        raise ValueError(f"{test_from} 到 {test_to} 之间没有开市日")
    if first < train_sessions:
        raise ValueError(f"第一个测试日 {calendar[first]} 之前只有 {first} 个开市日，"
                         f"训练窗要 {train_sessions} 个，还差 {train_sessions - first} 个")

    folds = []
    for number, start in enumerate(range(first, end, test_sessions), 1):
        stop = min(start + test_sessions, end)
        train_from = calendar[0] if expanding else calendar[start - train_sessions]
        folds.append(Fold(number, train_from, calendar[start - 1], calendar[start], calendar[stop - 1]))
    return folds


def training_days(sessions: Sequence[date], fold: Fold, *, label_sessions: int) -> list[date]:
    """The decision days whose samples may train `fold`'s model: those from
    its `train_from` on whose label ends — `label_sessions` sessions of the
    calendar `sessions` after the day — no later than its training cutoff."""
    calendar = sorted(set(sessions))
    start, known = bisect_left(calendar, fold.train_from), bisect_right(calendar, fold.train_to)
    return calendar[start:max(start, known - label_sessions)]
