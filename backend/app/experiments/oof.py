"""Out-of-fold scores (ticket 06a): each fold's model fitted on its own
training days alone, then scoring each session of its test stretch.

A session is scored on its own rows only — one `predict` per session — so a
trainer cannot see a later day's features while scoring an earlier one.
A fold whose fit or scoring raises is recorded as failed with the reason
and scores none of its sessions; the other folds go on. A row the trainer
gives no finite score has none.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from time import perf_counter

import numpy as np
import pandas as pd

from app.experiments.features import AS_OF
from app.experiments.folds import Fold, training_days
from app.experiments.trainers import ModelArtifact, Trainer, TrainingSet
from app.market_data.frame import CODE

SCORE_COLUMNS = [AS_OF, CODE, "score", "fold", "artifact_hash"]


@dataclass(frozen=True)
class FoldResult:
    fold: Fold
    samples: int                     # training samples the fit was handed
    seconds: float                   # fitting and scoring, wall clock
    artifact: ModelArtifact | None   # None when the fold failed
    error: str | None = None         # why it failed

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class OutOfFold:
    scores: pd.DataFrame       # SCORE_COLUMNS, a row per scored sample, by day then code
    folds: list[FoldResult]    # one per fold, in order


def out_of_fold(trainer: Trainer, folds: Sequence[Fold], features: pd.DataFrame, labels: pd.Series, *,
                sessions: Sequence[date], label_sessions: int) -> OutOfFold:
    """`features` and `labels` are indexed (as_of, code); a sample trains a
    fold when it has both and `training_days` lets its day in, by the
    trading calendar `sessions` and a label ending `label_sessions`
    sessions after its day. Every row of `features` on a session of a
    fold's test stretch is scored by that fold's model."""
    days = features.index.get_level_values(AS_OF)
    known = labels.reindex(features.index)
    labelled = known.notna().to_numpy()
    calendar = sorted(set(sessions))

    scored, results = [], []
    for fold in folds:
        trains = labelled & days.isin(training_days(calendar, fold, label_sessions=label_sessions))
        training = TrainingSet(features[trains], known[trains])
        tested = features[days.isin([day for day in calendar if fold.test_from <= day <= fold.test_to])]
        started = perf_counter()
        try:
            artifact = trainer.fit(training, fold.train_to)
            digest = artifact.hash()
            fold_scores = [_score(trainer, artifact, rows) for _, rows in tested.groupby(level=AS_OF, sort=True)]
        except Exception as error:  # the fold fails, the experiment goes on
            results.append(FoldResult(fold, int(trains.sum()), perf_counter() - started, None,
                                      f"{type(error).__name__}: {error}"))
            continue
        results.append(FoldResult(fold, int(trains.sum()), perf_counter() - started, artifact))
        scored += [rows.assign(fold=fold.number, artifact_hash=digest) for rows in fold_scores]

    if not scored:
        return OutOfFold(pd.DataFrame(columns=SCORE_COLUMNS), results)
    table = pd.concat(scored).reset_index()[SCORE_COLUMNS]
    return OutOfFold(table.sort_values([AS_OF, CODE], ignore_index=True), results)


def _score(trainer: Trainer, artifact: ModelArtifact, rows: pd.DataFrame) -> pd.DataFrame:
    """One session's rows scored, less those without a finite score."""
    scores = trainer.predict(artifact, rows).reindex(rows.index).astype(float)
    return scores[np.isfinite(scores.to_numpy())].rename("score").to_frame()
