"""Trainers (ticket 06a): `ridge_v1` standardises and fits on the training
set alone and scores from its JSON artifact, the same artifact and input
giving the same scores bit for bit; `rule_short_reversal_v1` fits nothing
and scores by the five-bar fall. `xgb_rank_ndcg_v1` (06b) grades each day's
labels into ten steps, groups its training by day, learns the day's order
and gives the same booster for the same training set, byte for byte."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.experiments import (
    AS_OF, FEATURE_NAMES, TRAINER_DEFAULTS, ModelArtifact, TrainingSet, build_trainer, feature_table,
)
from app.experiments.trainers import GRADES, TRAINER_SEARCH, grades
from app.market_data.frame import CODE
from tests.frames import sessions
from tests.random_bars import frame_from, walk

CUTOFF = date(2025, 6, 30)


def training_set(rows: int = 300, seed: int = 0) -> TrainingSet:
    """Random features; the label follows `ret_5` and `vol_20`, plus noise."""
    rng = np.random.default_rng(seed)
    days = sessions(rows // 10)
    index = pd.MultiIndex.from_tuples([(day, f"C{n}") for day in days for n in range(10)], names=[AS_OF, CODE])
    features = pd.DataFrame(rng.normal(0, 1, (len(index), len(FEATURE_NAMES))) * 0.05 + 1, index=index,
                            columns=list(FEATURE_NAMES))
    label = 0.3 * features["ret_5"] - 0.2 * features["vol_20"] + rng.normal(0, 0.001, len(index))
    return TrainingSet(features, label.rename("label"))


def test_the_defaults_are_a_single_ridge_alpha_and_no_parameters_for_the_rule() -> None:
    assert TRAINER_DEFAULTS["ridge_v1"] == {"alpha": 1.0} and TRAINER_DEFAULTS["rule_short_reversal_v1"] == {}


def test_ridge_v1_keeps_the_training_set_standardisation_and_its_fit_as_json() -> None:
    training = training_set()

    artifact = build_trainer("ridge_v1", {}).fit(training, CUTOFF)

    assert (artifact.trainer, artifact.params, artifact.train_cutoff, artifact.samples) == (
        "ridge_v1", {"alpha": 1.0}, CUTOFF, 300)
    assert artifact.state["features"] == list(FEATURE_NAMES)
    assert artifact.state["mean"] == training.features.to_numpy().mean(axis=0).tolist()
    assert artifact.state["std"] == training.features.to_numpy().std(axis=0).tolist()
    assert json.loads(json.dumps(artifact.as_dict())) == artifact.as_dict()


def test_ridge_v1_learns_the_relation_in_the_training_set() -> None:
    ridge = build_trainer("ridge_v1", {"alpha": 0.01})
    artifact = ridge.fit(training_set(seed=1), CUTOFF)
    fresh = training_set(seed=2)

    scores = ridge.predict(artifact, fresh.features)

    assert scores.index.equals(fresh.features.index)
    assert np.corrcoef(scores, fresh.labels)[0, 1] > 0.95
    coef = dict(zip(artifact.state["features"], artifact.state["coef"]))
    assert coef["ret_5"] > 0 > coef["vol_20"]


def test_ridge_v1_gives_the_same_scores_bit_for_bit_from_the_same_artifact_and_input() -> None:
    """Whether it is the artifact in hand, one read back from its JSON or a
    refit on the same training set; the features may come in any column
    order."""
    ridge = build_trainer("ridge_v1", {})
    training, fresh = training_set(seed=3), training_set(seed=4).features
    artifact = ridge.fit(training, CUTOFF)
    read_back = ModelArtifact.from_dict(json.loads(json.dumps(artifact.as_dict())))
    refit = build_trainer("ridge_v1", {}).fit(training, CUTOFF)

    scores = ridge.predict(artifact, fresh)

    for again in (ridge.predict(artifact, fresh), ridge.predict(read_back, fresh), ridge.predict(refit, fresh),
                  ridge.predict(artifact, fresh[list(reversed(FEATURE_NAMES))])):
        assert np.array_equal(again.to_numpy(), scores.to_numpy())
    assert artifact.hash() == read_back.hash() == refit.hash()


def test_the_artifact_hash_covers_the_trainer_parameters_state_and_cutoff() -> None:
    artifact = build_trainer("ridge_v1", {}).fit(training_set(), CUTOFF)
    others = [
        build_trainer("ridge_v1", {}).fit(training_set(), date(2025, 7, 1)),
        build_trainer("ridge_v1", {"alpha": 2}).fit(training_set(), CUTOFF),
        build_trainer("ridge_v1", {}).fit(training_set(seed=5), CUTOFF),
        ModelArtifact("other", artifact.params, artifact.state, CUTOFF, artifact.samples),
    ]

    assert len(artifact.hash()) == 64
    assert len({artifact.hash(), *(other.hash() for other in others)}) == 5
    assert ModelArtifact(artifact.trainer, artifact.params, artifact.state, CUTOFF, 1).hash() == artifact.hash()


def test_ridge_v1_takes_a_feature_that_never_moves_as_scaled_by_one() -> None:
    training = training_set()
    flat = TrainingSet(training.features.assign(volume_ratio=1.0), training.labels)

    artifact = build_trainer("ridge_v1", {}).fit(flat, CUTOFF)

    assert artifact.state["std"][FEATURE_NAMES.index("volume_ratio")] == 1.0
    assert np.isfinite(build_trainer("ridge_v1", {}).predict(artifact, flat.features)).all()


def test_ridge_v1_will_not_fit_on_nothing() -> None:
    empty = training_set()
    empty = TrainingSet(empty.features.iloc[:0], empty.labels.iloc[:0])

    with pytest.raises(ValueError, match="没有标签已知的训练样本"):
        build_trainer("ridge_v1", {}).fit(empty, CUTOFF)


def test_the_rule_baseline_fits_nothing_and_scores_the_five_bar_fall() -> None:
    days = sessions(70)
    features = feature_table(frame_from(walk(["A", "B", "C"], days, seed=6)), days[-3:])
    rule = build_trainer("rule_short_reversal_v1", {})

    artifact = rule.fit(training_set(), CUTOFF)

    assert (artifact.trainer, artifact.params, artifact.state, artifact.samples) == (
        "rule_short_reversal_v1", {}, {}, 300)
    pd.testing.assert_series_equal(rule.predict(artifact, features), -features["ret_5"], check_names=False)


def test_unknown_trainers_and_parameters_are_refused() -> None:
    with pytest.raises(ValueError, match="没有这个训练器：lightgbm"):
        build_trainer("lightgbm", {})
    with pytest.raises(ValueError, match="ridge_v1 没有这些参数：l1_ratio"):
        build_trainer("ridge_v1", {"l1_ratio": 0.5})
    with pytest.raises(ValueError, match="rule_short_reversal_v1 没有这些参数：alpha"):
        build_trainer("rule_short_reversal_v1", {"alpha": 1.0})
    for alpha in (0, -1, "1", True, float("nan")):
        with pytest.raises(ValueError, match="alpha 要是大于 0 的数"):
            build_trainer("ridge_v1", {"alpha": alpha})


def test_a_trainer_will_not_score_with_another_trainers_artifact() -> None:
    artifact = build_trainer("rule_short_reversal_v1", {}).fit(training_set(), CUTOFF)

    with pytest.raises(ValueError, match="ridge_v1 不能用 rule_short_reversal_v1 的模型工件打分"):
        build_trainer("ridge_v1", {}).predict(artifact, training_set().features)


def ranking_set(days: int = 40, per_day: int = 30, seed: int = 1, start: date = date(2025, 1, 6)) -> TrainingSet:
    """Random features; each day's label is `ret_5` plus a little noise, so
    the day's order follows `ret_5`."""
    rng = np.random.default_rng(seed)
    index = pd.MultiIndex.from_tuples([(day, f"C{n:02d}") for day in sessions(days, start) for n in range(per_day)],
                                      names=[AS_OF, CODE])
    features = pd.DataFrame(rng.normal(0, 0.05, (len(index), len(FEATURE_NAMES))), index=index,
                            columns=list(FEATURE_NAMES))
    label = features["ret_5"] + rng.normal(0, 0.005, len(index))
    return TrainingSet(features, label.rename("label"))


def test_a_days_labels_are_graded_into_ten_steps_within_the_day() -> None:
    days = sessions(2)
    index = pd.MultiIndex.from_tuples([(day, f"C{n:02d}") for day in days for n in range(20)], names=[AS_OF, CODE])
    # The second day's labels are a hundred times the first's: grading is within each day.
    labels = pd.Series([n / 100 for n in range(20)] + [n for n in range(20)], index=index, dtype=float)
    found = grades(labels)
    assert GRADES == 10
    assert list(found[:20]) == list(found[20:]) == [n // 2 for n in range(20)]
    tied = pd.Series([0.1, 0.1, 0.2, 0.3], index=index[:4], dtype=float)
    assert grades(tied)[0] == grades(tied)[1]


def test_the_ranker_groups_its_training_by_day_and_learns_the_days_order() -> None:
    trainer = build_trainer("xgb_rank_ndcg_v1", {"n_estimators": 200})
    artifact = trainer.fit(ranking_set(), CUTOFF)
    assert artifact.trainer == "xgb_rank_ndcg_v1" and artifact.samples == 40 * 30
    assert artifact.state["groups"] == 40 and artifact.state["features"] == list(FEATURE_NAMES)
    assert artifact.params["seed"] == 7 and artifact.params["threads"] == 4
    later = ranking_set(days=5, seed=2, start=date(2025, 9, 1))
    scores = trainer.predict(artifact, later.features)
    agreement = [scores[day.index].corr(day["ret_5"], method="spearman")
                 for _, day in later.features.groupby(level=AS_OF)]
    assert min(agreement) > 0.5 and np.mean(agreement) > 0.7


def test_the_same_training_set_gives_the_same_booster_byte_for_byte() -> None:
    trainer = build_trainer("xgb_rank_ndcg_v1", {"n_estimators": 30})
    first, second = trainer.fit(ranking_set(), CUTOFF), trainer.fit(ranking_set(), CUTOFF)
    assert first.hash() == second.hash() and first.state["booster"] == second.state["booster"]
    stored = ModelArtifact.from_dict(json.loads(json.dumps(first.as_dict())))
    rows = ranking_set(days=3, seed=3).features
    assert np.array_equal(trainer.predict(first, rows).to_numpy(), trainer.predict(stored, rows).to_numpy())
    assert first.hash() != build_trainer("xgb_rank_ndcg_v1", {"n_estimators": 30, "seed": 8}).fit(
        ranking_set(), CUTOFF).hash()


@pytest.mark.parametrize("params, why", [
    ({"max_depth": 0}, "max_depth"), ({"learning_rate": 0}, "learning_rate"), ({"subsample": 1.5}, "subsample"),
    ({"min_child_weight": -1}, "min_child_weight"), ({"threads": 0}, "threads"), ({"depth": 3}, "没有这些参数"),
])
def test_the_ranker_refuses_parameters_it_cannot_use(params, why) -> None:
    with pytest.raises(ValueError, match=why):
        build_trainer("xgb_rank_ndcg_v1", params)


def test_the_ranker_tries_four_parameter_sets_and_the_others_one() -> None:
    assert TRAINER_SEARCH["xgb_rank_ndcg_v1"] == [
        {"max_depth": 3, "n_estimators": 100}, {"max_depth": 3, "n_estimators": 200},
        {"max_depth": 4, "n_estimators": 100}, {"max_depth": 4, "n_estimators": 200}]
    assert TRAINER_SEARCH["ridge_v1"] == TRAINER_SEARCH["rule_short_reversal_v1"] == [{}]
