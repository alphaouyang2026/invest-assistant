"""A model experiment's contract and report, without a database: what the
contract freezes and implies on the calendar, the rank IC, the equally
weighted pool, and the evidence status with its reasons."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.experiments import build_trainer
from app.experiments.contract import FEATURE_BARS, contract_hash, freeze, models, plan, replays
from app.experiments.folds import Fold
from app.experiments.report import eligible_equal_weight, evidence, rank_ic

CALENDAR = [date(2025, 1, 1) + timedelta(days=n) for n in range(400)]  # every day a session, for the arithmetic


def frozen(**changes):
    request = {"test_from": CALENDAR[300].isoformat(), "test_to": CALENDAR[359].isoformat(), "train_sessions": 100,
               "test_sessions": 20, **changes}
    return freeze(request, sessions=CALENDAR, source=None, viewed_through=None, trainers=build_trainer)


def test_the_contract_implies_folds_decision_days_and_how_far_back_to_read():
    contract = frozen(rebalance_sessions=7)
    found = plan(contract, CALENDAR)
    assert [(f.test_from, f.test_to) for f in found.folds] == [
        (CALENDAR[300], CALENDAR[319]), (CALENDAR[320], CALENDAR[339]), (CALENDAR[340], CALENDAR[359])]
    assert found.test_days == CALENDAR[300:360]
    assert found.decision_days == CALENDAR[300:360:7]
    assert found.feature_days[0] == found.folds[0].train_from == CALENDAR[200]
    assert found.read_from == CALENDAR[200 - FEATURE_BARS]
    assert found.sessions[-1] == CALENDAR[359]
    # With an expanding window training starts at the calendar's first day: nothing earlier to read.
    assert plan(frozen(expanding=True), CALENDAR).read_from == CALENDAR[0]


def test_the_contract_records_its_defaults_and_its_hash_follows_any_change():
    contract = frozen()
    assert contract["portfolio_rules"] == {"initial_cash": "10000000", "max_positions": 10, "max_weight": "0.1",
                                           "cash_floor": "0.05", "max_adv20_fraction": "0.05"}
    assert contract["costs"] == {"commission_rate": "0.0", "commission_min": "0.0", "slippage": "0.001"}
    assert contract["task"]["label_sessions"] == 6 and contract["features"]["version"] == "ohlcv_ratios_v1"
    assert contract["minimums"] == {"coverage": 0.8, "training_samples": 20_000, "labelled_days": 24, "trades": 30}
    assert "max_adv20_fraction" not in frozen(max_adv20_fraction=None)["portfolio_rules"]
    assert contract_hash(contract) == contract_hash(frozen())
    assert contract_hash(contract) != contract_hash(frozen(name="另一个"))
    assert frozen(trainer_params={"alpha": 2})["model"]["params"] == {"alpha": 2.0}


def test_a_stress_scenario_adds_to_the_base_slippage_and_the_replays_follow():
    contract = frozen(slippage=0.002, stress_bps=[10.0, 25])
    assert contract["stress"]["scenarios"] == [{"extra_bps": "10", "slippage": "0.003"},
                                               {"extra_bps": "25", "slippage": "0.0045"}]
    assert "手续费" in contract["stress"]["basis"]
    assert frozen()["stress"]["scenarios"] == [{"extra_bps": "10", "slippage": "0.002"},
                                               {"extra_bps": "25", "slippage": "0.0035"},
                                               {"extra_bps": "50", "slippage": "0.006"}]
    assert [(m.key, m.role, m.label, m.trainer) for m in models(contract)] == [
        ("model", "model", "主模型", "ridge_v1"), ("baseline_1", "baseline", "规则基线 1", "rule_short_reversal_v1")]
    assert [(r.position, r.model.key, r.scenario, str(r.slippage), r.extra_bps) for r in replays(contract)] == [
        (1, "model", "base", "0.002", None), (2, "model", "stress", "0.003", 10),
        (3, "model", "stress", "0.0045", 25), (4, "baseline_1", "base", "0.002", None)]


@pytest.mark.parametrize("changes,match", [
    ({"train_sessions": 6}, "训练窗"),
    ({"rebalance_sessions": 0}, "决策日间隔"),
    ({"min_coverage": 1.5}, "最低覆盖率"),
    ({"expanding": "yes"}, "扩展训练窗"),
    ({"cash_floor": 1}, "现金下限"),
    ({"initial_cash": -1}, "初始资金"),
    ({"stress_bps": []}, "压力场景要有 1 到 5 个"),
    ({"stress_bps": [1, 2, 3, 4, 5, 6]}, "压力场景要有 1 到 5 个"),
    ({"stress_bps": [25, 10, 25.0]}, "不能重复：25 bps"),
    ({"stress_bps": [-5]}, "滑点加成"),
    ({"slippage": 0.095, "stress_bps": [50]}, "要小于 0.1"),
    ({"min_training_samples": -1}, "每折最少训练样本数"),
    ({"min_labelled_days": 1.5}, "最少有标签的决策日"),
    ({"actions": ["disposition", "priority", "leverage"]}, "不认识这些指令种类"),
])
def test_a_term_out_of_range_is_named(changes, match):
    with pytest.raises(ValueError, match=match):
        frozen(**changes)


def test_rank_ic_is_spearman_over_the_codes_with_both():
    scores = {"a": 3.0, "b": 2.0, "c": 1.0, "d": 0.0, "e": 5.0}
    labels = pd.Series({"a": 0.1, "b": 0.2, "c": -0.1, "d": -0.2, "x": 9.0})
    assert rank_ic(scores, labels) == (pytest.approx(0.8), 4)  # 1 − 6·2 ÷ (4·15)
    assert rank_ic({"a": 1.0, "b": 2.0}, labels) == (None, 2)
    assert rank_ic({"a": 1.0, "b": 1.0, "c": 1.0}, labels) == (None, 3)
    assert rank_ic(scores, None) == (None, 0)


def test_the_pool_averages_each_decision_days_universe_and_chains_the_periods():
    d1, d2, d3 = CALENDAR[:3]
    labels = {d1: pd.Series({"a": 0.10, "b": -0.02, "z": 5.0}), d2: pd.Series({"a": -0.05, "b": 0.01})}
    universes = {d1: ["a", "b"], d2: ["a", "b"], d3: ["a", "b"]}
    pool = eligible_equal_weight(labels, universes, [d1, d2, d3])
    assert [(p["date"], p["codes"]) for p in pool["periods"]] == [(d1.isoformat(), 2), (d2.isoformat(), 2)]
    assert pool["periods"][0]["mean_return"] == pytest.approx(0.04)
    assert pool["total_return"] == pytest.approx(1.04 * 0.98 - 1)
    assert eligible_equal_weight({}, universes, [d1])["total_return"] is None


FOLDS = [Fold(1, CALENDAR[0], CALENDAR[9], CALENDAR[10], CALENDAR[19]),
         Fold(2, CALENDAR[10], CALENDAR[19], CALENDAR[20], CALENDAR[29])]


def verdict(**changes):
    found = {"folds": FOLDS, "viewed_through": None, "failed": {"主模型（ridge_v1）": []},
             "samples": {1: 30_000, 2: 25_000}, "min_samples": 20_000, "coverage": 0.95, "min_coverage": 0.8,
             "ic_days": 30, "min_labelled_days": 24, "trades": 50, "min_trades": 30, **changes}
    return evidence(**found)


def test_the_verdict_is_never_passed_and_names_every_reason():
    assert verdict()["status"] == "exploratory"
    assert [r["code"] for r in verdict()["reasons"]] == ["framework_only"]
    seen = verdict(viewed_through=CALENDAR[20])
    assert (seen["status"], seen["viewed_folds"], seen["reasons"][0]["code"]) == (
        "exploratory", [1, 2], "history_viewed")
    partly = verdict(viewed_through=CALENDAR[15])
    assert partly["viewed_folds"] == [1] and partly["reasons"][0]["code"] == "history_partly_viewed"
    poor = verdict(failed={"主模型（ridge_v1）": [2], "规则基线 1（rule_short_reversal_v1）": [1]}, coverage=0.5,
                   ic_days=0, trades=0, samples={1: 900, 2: 25_000})
    assert poor["status"] == "insufficient_evidence"
    assert [r["code"] for r in poor["reasons"]] == [
        "fold_failed", "fold_failed", "too_few_training_samples", "coverage_below_minimum",
        "no_prediction_diagnostics", "zero_trades"]
    assert "第 2 折" in poor["reasons"][0]["message"]
    assert "第 1 折" in poor["reasons"][2]["message"] and "900" in poor["reasons"][2]["message"]
    assert [r["code"] for r in verdict(trades=3)["reasons"]] == ["too_few_trades"]
    assert [r["code"] for r in verdict(ic_days=10)["reasons"]] == ["too_few_labelled_days"]
    assert verdict(coverage=None)["reasons"][0]["code"] == "coverage_below_minimum"
