"""Out-of-fold scores (ticket 06a): each fold's model sees its training
days alone — every code of a day together, no label running past the
cutoff — and scores its test stretch a session at a time; bars after a day
change nothing about it; any trainer slots in; a fold that fails scores
nothing and the others go on."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.experiments import (
    AS_OF, SCORE_COLUMNS, Fold, ModelArtifact, TrainingSet, build_trainer, feature_table, label_sessions, labels,
    make_folds, out_of_fold,
)
from app.market_data import CLOSE, HIGH, LOW, OPEN, VOLUME
from app.market_data.frame import CODE, DATE
from tests.frames import sessions
from tests.random_bars import changed_after, frame_from, walk

DAYS = sessions(130)
CODES = [f"C{n}" for n in range(8)]
LABEL_SESSIONS = label_sessions()  # six


class Recording:
    """A stub trainer: scores by `ret_1`, and keeps what each fit saw."""

    name = "stub"

    def __init__(self, fail_on: date | None = None, fail_in: str = "fit") -> None:
        self.seen: dict[date, TrainingSet] = {}
        self.fail_on, self.fail_in = fail_on, fail_in

    def fit(self, training: TrainingSet, cutoff: date) -> ModelArtifact:
        self.seen[cutoff] = training
        if (cutoff, self.fail_in) == (self.fail_on, "fit"):
            raise RuntimeError("拟合发散")
        return ModelArtifact(self.name, {"feature": "ret_1"}, {"seen": len(training.labels)}, cutoff,
                             len(training.labels))

    def predict(self, artifact: ModelArtifact, features: pd.DataFrame) -> pd.Series:
        if (artifact.train_cutoff, self.fail_in) == (self.fail_on, "predict"):
            raise RuntimeError("打分出错")
        return features[artifact.params["feature"]]


def experiment(rows: list[dict[str, Any]] | None = None) -> tuple[pd.DataFrame, pd.Series, list[Fold]]:
    frame = frame_from(rows if rows is not None else walk(CODES, DAYS))
    folds = make_folds(DAYS, test_from=DAYS[90], test_to=DAYS[129], train_sessions=20, test_sessions=10)
    return feature_table(frame, DAYS), labels(frame, DAYS), folds


def run(trainer: Any, rows: list[dict[str, Any]] | None = None):
    features, found, folds = experiment(rows)
    return out_of_fold(trainer, folds, features, found, sessions=DAYS, label_sessions=LABEL_SESSIONS)


def test_each_fold_scores_every_code_on_each_session_of_its_test_stretch_under_its_artifact() -> None:
    features, found, folds = experiment()

    result = out_of_fold(build_trainer("ridge_v1", {}), folds, features, found, sessions=DAYS,
                         label_sessions=LABEL_SESSIONS)

    scores = result.scores
    assert list(scores.columns) == SCORE_COLUMNS == [AS_OF, CODE, "score", "fold", "artifact_hash"]
    assert [fold.number for fold in folds] == [1, 2, 3, 4]
    assert [(record.fold, record.failed, record.error) for record in result.folds] == [
        (fold, False, None) for fold in folds]
    for fold, record in zip(folds, result.folds):
        tested = scores[scores["fold"] == fold.number]
        stretch = [day for day in DAYS if fold.test_from <= day <= fold.test_to]
        assert sorted(set(tested[AS_OF])) == stretch
        assert len(tested) == len(stretch) * len(CODES)
        assert set(tested["artifact_hash"]) == {record.artifact.hash()}
        assert record.samples == record.artifact.samples == (20 - LABEL_SESSIONS) * len(CODES)
    assert list(scores[AS_OF]) == sorted(scores[AS_OF])
    assert np.isfinite(scores["score"].astype(float)).all()


def test_a_sample_whose_label_ends_after_the_training_cutoff_never_trains() -> None:
    """The cutoff is the session before the test stretch; the last six days
    before it have labels by now, but they run into the test stretch."""
    stub = Recording()
    features, found, folds = experiment()

    out_of_fold(stub, folds, features, found, sessions=DAYS, label_sessions=LABEL_SESSIONS)

    assert sorted(stub.seen) == [fold.train_to for fold in folds]
    for fold in folds:
        trained = sorted(set(stub.seen[fold.train_to].features.index.get_level_values(AS_OF)))
        assert trained[0] == fold.train_from
        assert all(DAYS[DAYS.index(day) + LABEL_SESSIONS] <= fold.train_to for day in trained)
        purged = DAYS[DAYS.index(fold.train_to) - LABEL_SESSIONS + 1:DAYS.index(fold.train_to) + 1]
        assert trained[-1] == DAYS[DAYS.index(purged[0]) - 1]
        assert all((day, code) in found.index for day in purged for code in CODES)  # labelled, and still left out
        training = stub.seen[fold.train_to]
        assert training.labels.index.equals(training.features.index)


def test_every_code_of_a_day_lands_in_the_same_fold() -> None:
    """In training, a day brings all its labelled codes; in testing, one
    fold scores all of a day's codes."""
    stub = Recording()
    features, found, folds = experiment()

    result = out_of_fold(stub, folds, features, found, sessions=DAYS, label_sessions=LABEL_SESSIONS)

    labelled = features.index.intersection(found.index)
    for training in stub.seen.values():
        for day, rows in training.features.groupby(level=AS_OF):
            assert set(rows.index.get_level_values(CODE)) == {code for when, code in labelled if when == day}
    assert (result.scores.groupby(AS_OF)["fold"].nunique() == 1).all()
    assert (result.scores.groupby(AS_OF)[CODE].nunique() == len(CODES)).all()


def test_bars_after_a_day_change_neither_its_features_nor_its_scores() -> None:
    """A day in the middle of the second fold's test stretch: prices and
    volume after it tripled, a code halted the next session and another
    delisted. Up to it, features and ridge scores are the same bit for bit;
    after it they are not."""
    day = DAYS[105]
    rows = walk(CODES, DAYS)

    def rewritten(row: dict) -> dict | None:
        if row[CODE] == "C7":
            return None
        if (row[CODE], row[DATE]) == ("C6", DAYS[106]):
            return dict(row, **{CLOSE: None})
        return dict(row, **{column: row[column] * 3 for column in (OPEN, HIGH, LOW, CLOSE, VOLUME)})

    changed = changed_after(rows, day, rewritten)
    before, after = run(build_trainer("ridge_v1", {}), rows), run(build_trainer("ridge_v1", {}), changed)

    up_to = lambda scores: scores[scores[AS_OF] <= day].reset_index(drop=True)  # noqa: E731
    assert len(up_to(before.scores)) == 16 * len(CODES)
    pd.testing.assert_frame_equal(up_to(before.scores), up_to(after.scores), check_exact=True)
    pd.testing.assert_frame_equal(experiment(rows)[0].loc[:day], experiment(changed)[0].loc[:day], check_exact=True)
    later = lambda scores: scores[scores[AS_OF] > day].reset_index(drop=True)  # noqa: E731
    assert not later(before.scores).equals(later(after.scores))


def test_a_stub_trainer_slots_in_with_nothing_else_changed() -> None:
    features, found, folds = experiment()

    result = out_of_fold(Recording(), folds, features, found, sessions=DAYS, label_sessions=LABEL_SESSIONS)

    scored = result.scores.set_index([AS_OF, CODE])["score"]
    assert scored.to_dict() == features.loc[scored.index, "ret_1"].to_dict()
    assert {record.artifact.trainer for record in result.folds} == {"stub"}


@pytest.mark.parametrize("fail_in", ["fit", "predict"])
def test_a_fold_that_raises_is_recorded_failed_and_scores_none_of_its_sessions(fail_in: str) -> None:
    features, found, folds = experiment()
    second = folds[1]

    result = out_of_fold(Recording(fail_on=second.train_to, fail_in=fail_in), folds, features, found,
                         sessions=DAYS, label_sessions=LABEL_SESSIONS)

    failed = result.folds[1]
    assert (failed.fold, failed.failed, failed.artifact) == (second, True, None)
    assert failed.error == {"fit": "RuntimeError: 拟合发散", "predict": "RuntimeError: 打分出错"}[fail_in]
    assert failed.samples == (20 - LABEL_SESSIONS) * len(CODES)
    assert [record.failed for record in result.folds] == [False, True, False, False]
    assert sorted(set(result.scores["fold"])) == [1, 3, 4]
    assert not result.scores[AS_OF].between(second.test_from, second.test_to).any()


def test_a_row_the_trainer_gives_no_finite_score_has_none() -> None:
    class Partial(Recording):
        def predict(self, artifact: ModelArtifact, features: pd.DataFrame) -> pd.Series:
            scores = features["ret_1"].copy()
            scores[scores.index.get_level_values(CODE) == "C0"] = np.nan
            scores[scores.index.get_level_values(CODE) == "C1"] = np.inf
            return scores.drop(index="C2", level=CODE)

    result = run(Partial())

    assert set(result.scores[CODE]) == set(CODES) - {"C0", "C1", "C2"}


def test_with_every_fold_failing_there_are_no_scores() -> None:
    class Failing(Recording):
        def fit(self, training: TrainingSet, cutoff: date) -> ModelArtifact:
            raise ValueError("不收敛")

    result = run(Failing())

    assert list(result.scores.columns) == SCORE_COLUMNS and result.scores.empty
    assert [record.error for record in result.folds] == ["ValueError: 不收敛"] * 4
