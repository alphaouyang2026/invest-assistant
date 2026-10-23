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
- `xgb_rank_ndcg_v1` (ticket 06b) learns the day's order itself: each
  training day is one group (XGBoost's query), its labels graded within the
  day into ten steps by decile (0 the worst tenth, 9 the best), and the
  trees fitted to rank a day's codes by NDCG with its pairs drawn from each
  code's nearest neighbours in the top (`rank:ndcg`, `topk` pairs). Its
  score orders a day's codes and says nothing of how much they will return.
  The booster is kept as XGBoost's own JSON inside the artifact; a fixed
  seed and thread count make the same training set give the same booster,
  byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import numpy as np
import pandas as pd
import xgboost as xgb
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


GRADES = 10  # the steps a day's labels are graded into for the ranker


class XgbRankNdcgV1:
    name = "xgb_rank_ndcg_v1"

    def __init__(self, params: Mapping[str, Any]) -> None:
        params = {**TRAINER_DEFAULTS[self.name], **params}
        self.params = {
            "max_depth": _count(self.name, "max_depth", params["max_depth"], 1),
            "n_estimators": _count(self.name, "n_estimators", params["n_estimators"], 1),
            "learning_rate": _share(self.name, "learning_rate", params["learning_rate"]),
            "subsample": _share(self.name, "subsample", params["subsample"]),
            "colsample_bytree": _share(self.name, "colsample_bytree", params["colsample_bytree"]),
            "min_child_weight": _positive(self.name, "min_child_weight", params["min_child_weight"]),
            "pairs_per_sample": _count(self.name, "pairs_per_sample", params["pairs_per_sample"], 1),
            "seed": _count(self.name, "seed", params["seed"], 0),
            "threads": _count(self.name, "threads", params["threads"], 1),
        }

    def fit(self, training: TrainingSet, cutoff: date) -> ModelArtifact:
        names = list(training.features.columns)
        frame = training.features.assign(label=training.labels.reindex(training.features.index)).sort_index()
        if frame.empty:
            raise ValueError(f"截至 {cutoff} 没有标签已知的训练样本")
        x, y = frame[names].to_numpy(float), frame["label"].to_numpy(float)
        if not (np.isfinite(x).all() and np.isfinite(y).all()):
            raise ValueError("训练样本里有缺失或无穷大的特征或标签")
        days = frame.index.get_level_values(0)
        group = pd.factorize(days, sort=True)[0]
        booster = xgb.train(self._booster_params(), xgb.DMatrix(x, label=grades(frame["label"]), qid=group,
                                                               feature_names=names),
                            num_boost_round=self.params["n_estimators"])
        state = {"features": names, "groups": int(group.max()) + 1, "booster": bytes(booster.save_raw("json")).decode()}
        return ModelArtifact(self.name, dict(self.params), state, cutoff, len(frame))

    def predict(self, artifact: ModelArtifact, features: pd.DataFrame) -> pd.Series:
        _check_trainer(self.name, artifact)
        names = list(artifact.state["features"])
        booster = xgb.Booster(params={"nthread": artifact.params["threads"]})
        booster.load_model(bytearray(artifact.state["booster"].encode()))
        scores = booster.predict(xgb.DMatrix(features[names].to_numpy(float), feature_names=names))
        return pd.Series(np.asarray(scores, float), index=features.index, name="score")

    def _booster_params(self) -> dict[str, Any]:
        p = self.params
        return {"objective": "rank:ndcg", "eval_metric": "ndcg@10", "tree_method": "hist",
                "lambdarank_pair_method": "topk", "lambdarank_num_pair_per_sample": p["pairs_per_sample"],
                "max_depth": p["max_depth"], "learning_rate": p["learning_rate"], "subsample": p["subsample"],
                "colsample_bytree": p["colsample_bytree"], "min_child_weight": p["min_child_weight"],
                "seed": p["seed"], "nthread": p["threads"]}


def grades(labels: pd.Series) -> np.ndarray:
    """Each label's step within its own day (the first index level): the
    share of the day's labels below it, cut into `GRADES` equal steps — 0
    the worst tenth, `GRADES − 1` the best. Ties share a rank."""
    by_day = labels.groupby(level=0)
    below = (by_day.rank(method="average") - 1) / by_day.transform("count")
    return np.minimum((below.to_numpy(float) * GRADES).astype(int), GRADES - 1)


_TRAINERS = {RidgeV1.name: RidgeV1, RuleShortReversalV1.name: RuleShortReversalV1, XgbRankNdcgV1.name: XgbRankNdcgV1}
TRAINER_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    RidgeV1.name: {"alpha": 1.0},
    RuleShortReversalV1.name: {},
    XgbRankNdcgV1.name: {"max_depth": 3, "n_estimators": 100, "learning_rate": 0.05, "subsample": 0.8,
                         "colsample_bytree": 0.8, "min_child_weight": 1.0, "pairs_per_sample": 10, "seed": 7,
                         "threads": 4},
}
# The parameter sets a model experiment tries on each fold's validation
# stretch when the trainer is the model under test: each overrides the
# trainer's parameters. One set means no search.
TRAINER_SEARCH: Mapping[str, Sequence[Mapping[str, Any]]] = {
    RidgeV1.name: [{}],
    RuleShortReversalV1.name: [{}],
    XgbRankNdcgV1.name: [{"max_depth": depth, "n_estimators": trees} for depth in (3, 4) for trees in (100, 200)],
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


def _count(trainer: str, what: str, value: Any, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or not float(value).is_integer() \
            or value < low:
        raise ValueError(f"{trainer} 的 {what} 要是不小于 {low} 的整数，收到 {value}")
    return int(value)


def _share(trainer: str, what: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= 1:
        raise ValueError(f"{trainer} 的 {what} 要大于 0、不大于 1，收到 {value}")
    return float(value)


def _positive(trainer: str, what: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value < float("inf"):
        raise ValueError(f"{trainer} 的 {what} 要是大于 0 的数，收到 {value}")
    return float(value)
