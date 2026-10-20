"""Date folds (ticket 06a): the test span cut end to end into stretches of
sessions, each trained on the sessions just before it, and a decision day
let into training only once its label has ended by the cutoff."""

from __future__ import annotations

from datetime import date

import pytest

from app.experiments import Fold, make_folds, training_days
from tests.frames import sessions

DAYS = sessions(40)  # weekdays from Monday 2025-01-06


def test_the_folds_cover_the_test_span_end_to_end_each_trained_up_to_the_session_before_it() -> None:
    folds = make_folds(DAYS, test_from=DAYS[20], test_to=DAYS[33], train_sessions=10, test_sessions=5)

    assert folds == [
        Fold(1, DAYS[10], DAYS[19], DAYS[20], DAYS[24]),
        Fold(2, DAYS[15], DAYS[24], DAYS[25], DAYS[29]),
        Fold(3, DAYS[20], DAYS[29], DAYS[30], DAYS[33]),  # the last is shorter
    ]


def test_ends_of_the_span_off_the_calendar_close_in_on_the_sessions_inside_it() -> None:
    """Saturday 11 January to Sunday 26 January: Monday the 13th to Friday
    the 24th."""
    folds = make_folds(DAYS, test_from=date(2025, 1, 11), test_to=date(2025, 1, 26),
                       train_sessions=5, test_sessions=10)

    assert folds == [Fold(1, DAYS[0], DAYS[4], DAYS[5], DAYS[14])]


def test_an_expanding_window_trains_every_fold_from_the_first_session() -> None:
    folds = make_folds(DAYS, test_from=DAYS[20], test_to=DAYS[33], train_sessions=10, test_sessions=5,
                       expanding=True)

    assert [(fold.train_from, fold.train_to) for fold in folds] == [
        (DAYS[0], DAYS[19]), (DAYS[0], DAYS[24]), (DAYS[0], DAYS[29])]


@pytest.mark.parametrize("expanding", [False, True])
def test_too_little_history_before_the_test_span_is_refused_saying_how_much_is_missing(expanding: bool) -> None:
    with pytest.raises(ValueError, match="之前只有 7 个开市日，训练窗要 10 个，还差 3 个"):
        make_folds(DAYS, test_from=DAYS[7], test_to=DAYS[20], train_sessions=10, test_sessions=5,
                   expanding=expanding)


def test_a_span_without_sessions_or_an_empty_window_is_refused() -> None:
    with pytest.raises(ValueError, match="之间没有开市日"):
        make_folds(DAYS, test_from=date(2025, 1, 11), test_to=date(2025, 1, 12), train_sessions=1, test_sessions=1)
    with pytest.raises(ValueError, match="晚于测试终点"):
        make_folds(DAYS, test_from=DAYS[30], test_to=DAYS[20], train_sessions=1, test_sessions=1)
    with pytest.raises(ValueError, match="至少 1 个开市日"):
        make_folds(DAYS, test_from=DAYS[20], test_to=DAYS[30], train_sessions=10, test_sessions=0)


def test_a_day_trains_a_fold_only_once_its_label_has_ended_by_the_cutoff() -> None:
    """A label ending six sessions after its day: the 14th day's ends on the
    cutoff, the 15th's on the first test session."""
    fold = Fold(1, DAYS[10], DAYS[19], DAYS[20], DAYS[24])

    assert training_days(DAYS, fold, label_sessions=6) == DAYS[10:14]
    assert training_days(DAYS, Fold(1, DAYS[0], DAYS[19], DAYS[20], DAYS[24]), label_sessions=6) == DAYS[:14]


def test_a_window_no_longer_than_the_label_trains_on_no_day() -> None:
    assert training_days(DAYS, Fold(1, DAYS[14], DAYS[19], DAYS[20], DAYS[24]), label_sessions=6) == []
