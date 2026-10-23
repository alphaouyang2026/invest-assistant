"""Out-of-fold scores (ticket 06a): each fold's model fitted on its own
training days alone, then scoring each session of its test stretch.

A session is scored on its own rows only — one `predict` per session — so a
trainer cannot see a later day's features while scoring an earlier one.
A fold whose fit or scoring raises is recorded as failed with the reason
and scores none of its sessions; the other folds go on. A row the trainer
gives no finite score has none.

With a search (ticket 06b) a fold first chooses among several parameter
sets: it holds out the last sessions of its training window as a
validation stretch, fits each set on the days before it — a day's sample
only when its label ends before the stretch starts, the same rule as the
fold's own training cutoff — scores the stretch a session at a time, and
keeps the set whose top `top_n` codes beat the day's scored codes by the
most on average (the label's mean over them less its mean over all; the
earlier set on a tie). It then fits the kept set on the whole training
window and scores the test stretch with that. Every set tried is
recorded, the failed ones too; a fold where none can be compared fails.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from app.experiments.features import AS_OF
from app.experiments.folds import Fold, training_days
from app.experiments.trainers import ModelArtifact, Trainer, TrainingSet
from app.market_data.frame import CODE

SCORE_COLUMNS = [AS_OF, CODE, "score", "fold", "artifact_hash"]


@dataclass(frozen=True)
class Search:
    """How a fold chooses its model's parameters (ticket 06b)."""

    candidates: Sequence[Trainer]  # one per parameter set to try, in order
    validation_sessions: int       # the training window's last sessions, held out to choose on
    top_n: int                     # how many of a day's best-scored codes the choice looks at


@dataclass(frozen=True)
class FoldResult:
    fold: Fold
    samples: int                     # training samples the fit was handed
    seconds: float                   # choosing, fitting and scoring, wall clock
    artifact: ModelArtifact | None   # None when the fold failed
    error: str | None = None         # why it failed
    search: list[dict[str, Any]] | None = None  # every parameter set tried, with how it did; None without a search

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class OutOfFold:
    scores: pd.DataFrame       # SCORE_COLUMNS, a row per scored sample, by day then code
    folds: list[FoldResult]    # one per fold, in order


def out_of_fold(model: Trainer | Search, folds: Sequence[Fold], features: pd.DataFrame, labels: pd.Series, *,
                sessions: Sequence[date], label_sessions: int) -> OutOfFold:
    """`features` and `labels` are indexed (as_of, code); a sample trains a
    fold when it has both and `training_days` lets its day in, by the
    trading calendar `sessions` and a label ending `label_sessions`
    sessions after its day. Every row of `features` on a session of a
    fold's test stretch is scored by that fold's model — `model` itself, or
    the candidate a `Search` keeps for the fold."""
    days = features.index.get_level_values(AS_OF)
    known = labels.reindex(features.index)
    labelled = known.notna().to_numpy()
    calendar = sorted(set(sessions))

    def training(fold: Fold) -> np.ndarray:
        return labelled & days.isin(training_days(calendar, fold, label_sessions=label_sessions))

    def on(start: date, end: date) -> np.ndarray:
        return days.isin([day for day in calendar if start <= day <= end])

    scored, results = [], []
    for fold in folds:
        trains = training(fold)
        started, tried = perf_counter(), None
        try:
            trainer = model
            if isinstance(model, Search):
                tried = _try(model, fold, calendar, training, features, known)
                trainer = _keep(model, fold, tried)
            artifact = trainer.fit(TrainingSet(features[trains], known[trains]), fold.train_to)
            digest = artifact.hash()
            tested = features[on(fold.test_from, fold.test_to)]
            fold_scores = [_score(trainer, artifact, rows) for _, rows in tested.groupby(level=AS_OF, sort=True)]
        except Exception as error:  # the fold fails, the experiment goes on
            results.append(FoldResult(fold, int(trains.sum()), perf_counter() - started, None,
                                      f"{type(error).__name__}: {error}", tried))
            continue
        results.append(FoldResult(fold, int(trains.sum()), perf_counter() - started, artifact, search=tried))
        scored += [rows.assign(fold=fold.number, artifact_hash=digest) for rows in fold_scores]

    if not scored:
        return OutOfFold(pd.DataFrame(columns=SCORE_COLUMNS), results)
    table = pd.concat(scored).reset_index()[SCORE_COLUMNS]
    return OutOfFold(table.sort_values([AS_OF, CODE], ignore_index=True), results)


def validation_fold(fold: Fold, calendar: Sequence[date], sessions: int) -> Fold:
    """The fold a search fits its candidates on: the training window up to
    the session before its last `sessions` sessions, which it is tested
    on. ValueError when the window has no room for them."""
    window = [day for day in calendar if fold.train_from <= day <= fold.train_to]
    if len(window) <= sessions:
        raise ValueError(f"第 {fold.number} 折的训练窗只有 {len(window)} 个开市日，放不下 {sessions} 个开市日的验证段")
    return Fold(fold.number, fold.train_from, window[-sessions - 1], window[-sessions], fold.train_to)


def top_n_excess(scores: pd.Series, labels: pd.Series, top_n: int) -> float | None:
    """How much the day's `top_n` best-scored codes beat all of its scored
    codes: their labels' mean less the mean over all with a label; None
    when fewer than `top_n` codes have both."""
    both = pd.DataFrame({"score": scores, "label": labels}).dropna()
    if len(both) < top_n or top_n < 1:
        return None
    best = both.sort_values(["score"], ascending=False, kind="stable").head(top_n)
    return float(best["label"].mean() - both["label"].mean())


def _try(search: Search, fold: Fold, calendar: Sequence[date], training: Callable[[Fold], np.ndarray],
         features: pd.DataFrame, known: pd.Series) -> list[dict[str, Any]]:
    """Each candidate fitted before the fold's validation stretch and
    measured on it: a record of every one, in order."""
    inner = validation_fold(fold, calendar, search.validation_sessions)
    fits = training(inner)
    # Validation days: the stretch's days whose labels are known by the fold's own cutoff.
    checks = training(fold) & features.index.get_level_values(AS_OF).isin(
        [day for day in calendar if inner.test_from <= day <= inner.test_to])
    tried = []
    for trainer in search.candidates:
        record: dict[str, Any] = {"params": dict(getattr(trainer, "params", {})), "samples": int(fits.sum())}
        try:
            artifact = trainer.fit(TrainingSet(features[fits], known[fits]), inner.train_to)
            excesses = []
            for _, rows in features[checks].groupby(level=AS_OF, sort=True):
                scores = _score(trainer, artifact, rows)["score"]
                excess = top_n_excess(scores, known.reindex(rows.index), search.top_n)
                if excess is not None:
                    excesses.append(excess)
            record.update(validation=float(np.mean(excesses)) if excesses else None, days=len(excesses), error=None)
        except Exception as error:
            record.update(validation=None, days=0, error=f"{type(error).__name__}: {error}")
        tried.append(record)
    return tried


def _keep(search: Search, fold: Fold, tried: list[dict[str, Any]]) -> Trainer:
    """The candidate that did best on the validation stretch, marked in
    `tried`; the earlier on a tie. ValueError when none could be compared."""
    compared = [n for n, record in enumerate(tried) if record["validation"] is not None]
    for record in tried:
        record["chosen"] = False
    if not compared:
        raise ValueError(f"第 {fold.number} 折的验证段上没有一组参数能比较：" +
                         "；".join(r["error"] or "没有足够的有标签证券" for r in tried))
    best = max(compared, key=lambda n: (tried[n]["validation"], -n))
    tried[best]["chosen"] = True
    return search.candidates[best]


def _score(trainer: Trainer, artifact: ModelArtifact, rows: pd.DataFrame) -> pd.DataFrame:
    """One session's rows scored, less those without a finite score."""
    scores = trainer.predict(artifact, rows).reindex(rows.index).astype(float)
    return scores[np.isfinite(scores.to_numpy())].rename("score").to_frame()
