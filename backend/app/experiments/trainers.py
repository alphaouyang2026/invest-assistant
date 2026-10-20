"""Trainers (ticket 06a): the one seam a model experiment fits and scores
through, so that swapping the learner changes nothing in the folds, the
replays or the report.

`fit` sees one fold's training set alone and hands back a model artifact:
the trainer, its frozen parameters and what fitting worked out, as JSON —
no pickle — with a hash over all of it and the training cutoff. `predict`
works from the artifact alone, so the same artifact scores the same
features the same way, bit for bit, wherever it is read back.

- `ridge_v1` standardises each feature by its mean and standard deviation
  over the training set, then fits a ridge regression of the label on them
  (scikit-learn's `Ridge`, a single `alpha`, no search). It scores in numpy
  from the stored state, a feature at a time in a fixed order.
- `rule_short_reversal_v1` is the rule baseline: it fits nothing and scores
  a sample by how far it fell over the last five bars (`−ret_5`) — ticket
  05's short reversal ranking.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


@dataclass(frozen=True)
class TrainingSet:
    features: pd.DataFrame  # indexed (as_of, code), a column per feature
    labels: pd.Series       # the same index


@dataclass(frozen=True)
class ModelArtifact:
    trainer: str                 # the trainer's name: "ridge_v1", "rule_short_reversal_v1", a test stub…
    params: Mapping[str, Any]    # its frozen hyperparameters
    state: Mapping[str, Any]     # what fitting worked out, JSON-ready
    train_cutoff: date           # the fold's training cutoff
    samples: int                 # how many samples it was fitted on

    def hash(self) -> str:
        """sha256 of the canonical JSON of the trainer, its parameters, its
        state and the training cutoff."""
        content = {"trainer": self.trainer, "params": self.params, "state": self.state,
                   "train_cutoff": self.train_cutoff.isoformat()}
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready, for keeping; `from_dict` reads it back."""
        return {"trainer": self.trainer, "params": dict(self.params), "state": dict(self.state),
                "train_cutoff": self.train_cutoff.isoformat(), "samples": self.samples}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModelArtifact:
        return cls(data["trainer"], data["params"], data["state"], date.fromisoformat(data["train_cutoff"]),
                   data["samples"])


class Trainer(Protocol):
    name: str

    def fit(self, training: TrainingSet, cutoff: date) -> ModelArtifact: ...

    def predict(self, artifact: ModelArtifact, features: pd.DataFrame) -> pd.Series:
        """A score per row of `features`, on its index (as_of, code); higher
        ranks first."""
        ...


class RidgeV1:
    name = "ridge_v1"

    def __init__(self, params: Mapping[str, Any]) -> None:
        params = {**TRAINER_DEFAULTS[self.name], **params}
        alpha = params["alpha"]
        if not (isinstance(alpha, int | float) and not isinstance(alpha, bool) and 0 < alpha < float("inf")):
            raise ValueError(f"{self.name} 的 alpha 要是大于 0 的数，收到 {alpha}")
        self.params = {"alpha": float(alpha)}

    def fit(self, training: TrainingSet, cutoff: date) -> ModelArtifact:
        names = list(training.features.columns)
        x = training.features.to_numpy(float)
        y = training.labels.reindex(training.features.index).to_numpy(float)
        if not len(x):
            raise ValueError(f"截至 {cutoff} 没有标签已知的训练样本")
        if not (np.isfinite(x).all() and np.isfinite(y).all()):
            raise ValueError("训练样本里有缺失或无穷大的特征或标签")
        mean, std = x.mean(axis=0), x.std(axis=0)
        std = np.where(std > 0, std, 1.0)  # a feature that never moves only shifts the intercept
        model = Ridge(alpha=self.params["alpha"], solver="cholesky").fit((x - mean) / std, y)
        state = {"features": names, "mean": mean.tolist(), "std": std.tolist(),
                 "coef": np.asarray(model.coef_, float).tolist(), "intercept": float(model.intercept_)}
        return ModelArtifact(self.name, dict(self.params), state, cutoff, len(x))

    def predict(self, artifact: ModelArtifact, features: pd.DataFrame) -> pd.Series:
        _check_trainer(self.name, artifact)
        state = artifact.state
        x = features[list(state["features"])].to_numpy(float)
        scores = np.full(len(x), float(state["intercept"]))
        for column, (mean, std, coef) in enumerate(zip(state["mean"], state["std"], state["coef"], strict=True)):
            scores = scores + (x[:, column] - mean) / std * coef
        return pd.Series(scores, index=features.index, name="score")


class RuleShortReversalV1:
    name = "rule_short_reversal_v1"

    def __init__(self, params: Mapping[str, Any]) -> None:
        self.params: dict[str, Any] = {}

    def fit(self, training: TrainingSet, cutoff: date) -> ModelArtifact:
        return ModelArtifact(self.name, {}, {}, cutoff, len(training.labels))

    def predict(self, artifact: ModelArtifact, features: pd.DataFrame) -> pd.Series:
        _check_trainer(self.name, artifact)
        return (-features["ret_5"].astype(float)).rename("score")


_TRAINERS = {RidgeV1.name: RidgeV1, RuleShortReversalV1.name: RuleShortReversalV1}
TRAINER_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    RidgeV1.name: {"alpha": 1.0},
    RuleShortReversalV1.name: {},
}


def build_trainer(name: str, params: Mapping[str, Any]) -> Trainer:
    """`params` override the defaults; a name or parameter the trainer does
    not have is refused rather than ignored."""
    if name not in _TRAINERS:
        raise ValueError(f"没有这个训练器：{name}")
    unknown = sorted(set(params) - set(TRAINER_DEFAULTS[name]))
    if unknown:
        raise ValueError(f"{name} 没有这些参数：{', '.join(unknown)}")
    return _TRAINERS[name](params)


def _check_trainer(name: str, artifact: ModelArtifact) -> None:
    if artifact.trainer != name:
        raise ValueError(f"{name} 不能用 {artifact.trainer} 的模型工件打分")
