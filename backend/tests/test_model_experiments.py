"""Model experiments (ticket 06a) end to end on the synthetic market of
`tests/experiment_market.py`: three ten-session test folds from S100 to
S129 on a 30-session rolling window, decisions every five sessions from
S100, three positions. The job reads, scores out of fold, replays through
score top-N on the paper accounts' own trading day, and stores it all."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import func, select, text, update

from app.accounts import Accounts, AccountSpec, Costs, PortfolioRules
from app.accounts import tables as account_tables
from app.experiments import ModelArtifact, build_trainer
from app.experiments import service as service_module
from app.experiments import tables as db
from app.experiments.service import ModelExperiments
from app.jobs import Jobs
from app.market_data import tables as market_tables
from app.strategies import Disposition, ScoreTable, ScoreTopN
from tests.account_market import Script
from tests.experiment_market import CODES, SESSIONS, TEST_FROM, TEST_TO, experiment_market, request

S = SESSIONS
DECISION_DAYS = S[100:130:5]
FOLD_TESTS = [(S[100], S[109]), (S[110], S[119]), (S[120], S[129])]


class Stub:
    """A trainer that notes what it is handed, scores by `ret_20` and fails
    any fold whose cutoff is in `fail_at`."""

    name = "stub_v1"

    def __init__(self, fail_at=()) -> None:
        self.params: dict = {}
        self.fail_at = set(fail_at)
        self.fits: list[tuple[date, pd.DataFrame, pd.Series]] = []
        self.predictions: list[tuple[date, pd.Index]] = []

    def fit(self, training, cutoff):
        self.fits.append((cutoff, training.features, training.labels))
        if cutoff in self.fail_at:
            raise RuntimeError("桩训练失败")
        return ModelArtifact(self.name, {}, {"rows": len(training.labels)}, cutoff, len(training.labels))

    def predict(self, artifact, features):
        self.predictions.append((artifact.train_cutoff, features.index))
        return features["ret_20"].rename("score")


def with_stub(stub: Stub):
    return lambda name, params: stub if name == stub.name else build_trainer(name, params)


@pytest.fixture
def env(migrated_database, tmp_path):
    market = experiment_market(migrated_database)
    jobs = Jobs(tmp_path)
    jobs.start()
    yield SimpleNamespace(engine=migrated_database, market=market, jobs=jobs,
                          experiments=ModelExperiments(migrated_database, market, jobs))
    jobs.stop()


def run(env, experiments: ModelExperiments | None = None, **changes) -> dict:
    experiments = experiments or env.experiments
    experiment_id = experiments.submit(request(**changes), str(uuid4()))
    assert env.jobs.wait_until_idle(60)
    found = experiments.get(experiment_id)
    assert found["status"] == "completed", found["error"]
    return found


def all_days(experiments, experiment_id, position=1) -> list[dict]:
    return experiments.days(experiment_id, position, page_size=100)["days"]


def all_orders(experiments, experiment_id, position=1) -> list[dict]:
    return list(reversed(experiments.orders(experiment_id, position, page_size=200)["orders"]))


def stored_scores(engine, experiment_id, model="model") -> dict[date, dict[str, float]]:
    with engine.connect() as con:
        rows = con.execute(select(db.scores.c.as_of, db.scores.c.scores).where(
            db.scores.c.experiment_id == experiment_id, db.scores.c.model == model)).all()
    return {date.fromisoformat(day): scores for day, scores in rows}


def test_an_experiment_freezes_its_contract_scores_out_of_fold_and_replays_five_times(env):
    found = run(env)
    contract, report = found["contract"], found["report"]
    assert contract["model"] == {"trainer": "ridge_v1", "params": {"alpha": 1.0}, "search_budget": 1}
    assert contract["baselines"] == [{"trainer": "rule_short_reversal_v1", "params": {}}]
    assert contract["policy"]["anchor"] == TEST_FROM.isoformat() and contract["policy"]["rebalance_sessions"] == 5
    assert contract["portfolio_rules"]["max_adv20_fraction"] == "0.05"
    assert contract["stress_slippages"] == ["0.001", "0.0025", "0.005"]
    assert contract["actions"] == ["disposition", "priority"] and contract["viewed_through"] is None
    assert found["contract_hash"] == report["contract_hash"]
    assert found["input_fingerprint"]["from"] == S[9].isoformat()  # 61 bars before the first training day S70
    assert found["input_fingerprint"]["through"] == TEST_TO.isoformat()

    # Folds: each model's artifact kept as JSON, its hash re-derivable from it.
    assert [(f["test_from"], f["test_to"]) for f in report["folds"]] == [
        (a.isoformat(), b.isoformat()) for a, b in FOLD_TESTS]
    assert len(found["fold_results"]) == 6 and not any(f["error"] for f in found["fold_results"])
    for result in found["fold_results"]:
        assert ModelArtifact.from_dict(result["artifact"]).hash() == result["artifact_hash"]
        assert result["artifact"]["train_cutoff"] == result["train_to"]

    # Only the decision days' scores are kept, every code of the universe scored.
    scores = stored_scores(env.engine, found["id"])
    assert sorted(scores) == DECISION_DAYS
    assert all(sorted(day_scores) == CODES for day_scores in scores.values())

    # Five replays: the model at the base costs and each stress slippage, the baseline at the base.
    shapes = [(r["position"], r["model"], r["scenario"], r["costs"]["slippage"]) for r in report["replays"]]
    assert shapes == [(1, "model", "base", "0.001"), (2, "model", "stress", "0.001"),
                      (3, "model", "stress", "0.0025"), (4, "model", "stress", "0.005"),
                      (5, "baseline_1", "base", "0.001")]
    base, stressed = all_orders(env.experiments, found["id"], 1), all_orders(env.experiments, found["id"], 3)
    assert base == all_orders(env.experiments, found["id"], 2)  # 10 bps is the base slippage here
    first_buy = next(o for o in stressed if o["kind"] == "buy" and o["status"] == "filled")
    with env.engine.connect() as con:
        opened = con.execute(select(market_tables.daily_bars.c.open).where(
            market_tables.daily_bars.c.code == first_buy["code"],
            market_tables.daily_bars.c.date == date.fromisoformat(first_buy["execution_date"]))).scalar_one()
    assert first_buy["fill_price"] == pytest.approx(float(opened * Decimal("1.0025")))
    metrics = [r["metrics"] for r in report["replays"]]
    assert metrics[1]["total_return"] > metrics[2]["total_return"] > metrics[3]["total_return"]

    # Buys are only ever planned on decision days, for codes the model scored.
    for order in base:
        if order["kind"] == "buy":
            assert date.fromisoformat(order["signal_date"]) in DECISION_DAYS
            assert order["reason"]["reason_codes"] == ["model_rank"]
            assert order["priority"] == scores[date.fromisoformat(order["signal_date"])][order["code"]]

    # Every replayed day is recorded, its NAV and cash those of the replay.
    replay = env.experiments.replay(found["id"], 1)["result"]
    days = all_days(env.experiments, found["id"])
    assert [d["date"] for d in days] == [p["date"] for p in replay["nav"]] == [d.isoformat() for d in S[100:130]]
    assert [(d["nav"], d["cash"]) for d in days] == [(p["nav"], p["cash"]) for p in replay["nav"]]
    assert [d["date"] for d in days if d["decision_day"]] == [d.isoformat() for d in DECISION_DAYS]
    assert all(d["holdings_decisions"] == [] or {h["reason_codes"][0] for h in d["holdings_decisions"]} == {"not_check_day"}
               for d in days if not d["decision_day"])
    first = days[0]
    assert first["model_available"] and first["scored"] == first["universe"] == len(CODES)
    assert [s["code"] for s in first["top_scores"][:3]] == [o["code"] for o in first["orders"]]
    assert [t["code"] for t in first["target"]] == sorted(o["code"] for o in first["orders"])
    assert first["constraints"]["unplaced_candidates"] == len(CODES) - 3
    assert days[1]["executions"] and {e["status"] for e in days[1]["executions"]} == {"filled"}
    assert [h["code"] for h in days[1]["holdings"]] == [t["code"] for t in first["target"]]

    # The report: TOPIX, the equal-weighted pool, diagnostics for each model, and the verdict.
    assert report["benchmarks"]["topix_price"]["total_return"] == metrics[0]["topix_return"]
    pool = report["benchmarks"]["eligible_equal_weight"]
    assert [p["date"] for p in pool["periods"]] == [d.isoformat() for d in DECISION_DAYS[:5]]  # S125's label ends after S129
    model = report["models"][0]["diagnostics"]
    assert model["decision_days"] == 6 and model["coverage_mean"] == 1 and model["ic_days"] == 5
    assert [f["fold"] for f in model["folds"]] == [1, 2, 3]
    assert report["evidence"]["status"] == "exploratory"
    assert [r["code"] for r in report["evidence"]["reasons"]] == ["framework_only"]
    assert len(replay["nav"]) == report["sessions"] == 30


def test_training_sees_only_labels_known_by_its_cutoff_and_whole_days(env):
    stub = Stub()
    experiments = ModelExperiments(env.engine, env.market, env.jobs, trainers=with_stub(stub))
    found = run(env, experiments, trainer="stub_v1")
    assert found["contract"]["model"]["trainer"] == "stub_v1"
    assert {f["artifact"]["trainer"] for f in found["fold_results"] if f["model"] == "model"} == {"stub_v1"}

    calendar = list(S)
    for (cutoff, features, labels), (test_from, test_to) in zip(stub.fits, FOLD_TESTS, strict=True):
        assert cutoff == calendar[calendar.index(test_from) - 1]
        days = sorted(set(features.index.get_level_values("as_of")))
        # A sample's label ends six sessions after its day: never after the cutoff.
        assert max(calendar[calendar.index(day) + 6] for day in days) == cutoff
        assert days[0] == calendar[calendar.index(test_from) - 30]  # the rolling window's first day
        # Every day trains whole: each code that has features and a label that day.
        assert all(len(features.xs(day, level="as_of")) == len(CODES) for day in days)
        assert labels.index.equals(features.index)
    # Scoring is a session at a time, by the fold the session is in, whole.
    for cutoff, index in stub.predictions:
        (day,) = set(index.get_level_values("as_of"))
        fold = next(n for n, (a, b) in enumerate(FOLD_TESTS) if a <= day <= b)
        assert cutoff == stub.fits[fold][0] and len(index) == len(CODES)


def test_later_market_changes_change_neither_earlier_scores_nor_earlier_decisions(env):
    before = run(env)
    after_day = S[112]  # inside fold 2's test stretch, after its cutoff S109
    with env.engine.begin() as con:
        con.execute(text("UPDATE daily_bars SET open = CAST(open AS REAL) * 2, high = CAST(high AS REAL) * 2, "
                         "low = CAST(low AS REAL) * 2, close = CAST(close AS REAL) * 2 "
                         "WHERE date > :day AND code IN (" + ", ".join(f"'{c}'" for c in CODES[:6]) + ")"),
                    {"day": after_day.isoformat()})
    after = run(env)
    assert after["input_fingerprint"]["sha256"] != before["input_fingerprint"]["sha256"]
    old, new = stored_scores(env.engine, before["id"]), stored_scores(env.engine, after["id"])
    assert {d: s for d, s in old.items() if d <= after_day} == {d: s for d, s in new.items() if d <= after_day}
    assert any(old[d] != new[d] for d in old if d > after_day)

    def decided(days):
        return [(d["date"], d["holdings_decisions"], d["target"], d["candidates"],
                 [(o["kind"], o["code"], o["planned_quantity"], o["reason_codes"]) for o in d["orders"]])
                for d in days if date.fromisoformat(d["date"]) <= after_day]
    assert decided(all_days(env.experiments, before["id"])) == decided(all_days(env.experiments, after["id"]))


def test_the_frozen_scores_through_a_paper_account_trade_as_the_experiment_replayed(env):
    found = run(env)
    table = ScoreTable(frozenset(DECISION_DAYS), stored_scores(env.engine, found["id"]))
    accounts = Accounts(env.engine, env.market, build_strategy=lambda name, params: ScoreTopN(table, params))
    rules = PortfolioRules(max_positions=3, max_weight=Decimal("0.3"), cash_floor=Decimal("0.05"),
                           max_adv20_fraction=Decimal("0.05"))
    account = accounts.create(AccountSpec("冻结分数", "score_top_n_v1", TEST_FROM, rules=rules,
                                          costs=Costs(slippage=Decimal("0.001"))))
    accounts.advance(account, through=TEST_TO)
    report = accounts.report(account)

    replayed = all_orders(env.experiments, found["id"])
    assert len(replayed) == len(report.orders) > 0
    for mine, theirs in zip(replayed, report.orders, strict=True):
        assert (mine["kind"], mine["code"], mine["signal_date"], mine["execution_date"], mine["planned_quantity"],
                mine["status"], mine["outcome_reason"], mine["filled_quantity"], mine["reason"]) == (
            theirs.kind, theirs.code, theirs.signal_date.isoformat(), theirs.execution_date.isoformat(),
            theirs.planned_quantity, theirs.status, theirs.outcome_reason, theirs.filled_quantity, dict(theirs.reason))
        assert mine["fill_price"] == (None if theirs.fill_price is None else float(theirs.fill_price))
    nav = env.experiments.replay(found["id"], 1)["result"]["nav"]
    assert [p["nav"] for p in nav] == [float(v) for v in report.nav]


def test_a_fold_that_fails_opens_nothing_on_its_decision_days_and_keeps_what_is_held(env):
    stub = Stub(fail_at={S[109]})  # fold 2
    experiments = ModelExperiments(env.engine, env.market, env.jobs, trainers=with_stub(stub))
    found = run(env, experiments, trainer="stub_v1")
    failed = [f for f in found["fold_results"] if f["error"]]
    assert [(f["model"], f["fold"], f["artifact"]) for f in failed] == [("model", 2, None)]
    assert "桩训练失败" in failed[0]["error"]
    assert sorted(stored_scores(env.engine, found["id"])) == [S[100], S[105], S[120], S[125]]

    days = {d["date"]: d for d in all_days(experiments, found["id"])}
    held_before = [h["code"] for h in days[S[109].isoformat()]["holdings"]]
    assert held_before
    for day in (S[110], S[115]):
        record = days[day.isoformat()]
        assert record["model_available"] is False and record["scored"] == 0
        assert {(h["disposition"], tuple(h["reason_codes"])) for h in record["holdings_decisions"]} == {
            ("hold", ("model_unavailable",))}
        assert record["orders"] == []
    for day in S[110:120]:
        assert [h["code"] for h in days[day.isoformat()]["holdings"]] == held_before
    assert days[S[120].isoformat()]["orders"]  # trading resumes with fold 3

    report = found["report"]
    assert report["models"][0]["failed_folds"] == [2]
    assert report["models"][0]["diagnostics"]["unavailable_days"] == 2
    assert report["evidence"]["status"] == "insufficient_evidence"
    assert {"fold_failed", "coverage_below_minimum"} <= {r["code"] for r in report["evidence"]["reasons"]}


def test_a_failed_experiment_is_kept_and_retried_as_a_new_one_unless_its_input_changed(env, monkeypatch):
    real = service_module.replay_range
    calls = []

    def breaks_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("回放中断")
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "replay_range", breaks_once)
    first = env.experiments.submit(request(), str(uuid4()))
    assert env.jobs.wait_until_idle(60)
    failed = env.experiments.get(first)
    assert (failed["status"], failed["error"], failed["report"]) == ("failed", "回放中断", None)
    assert failed["input_fingerprint"] is not None

    second = env.experiments.submit({}, str(uuid4()), retry_of=first)
    assert env.jobs.wait_until_idle(60)
    retried = env.experiments.get(second)
    assert (retried["status"], retried["retry_of"], retried["contract"]) == ("completed", first, failed["contract"])
    assert env.experiments.get(first)["status"] == "failed"
    assert env.experiments.get(first)["retried_by"] == [second]
    with pytest.raises(ValueError, match="只有失败"):
        env.experiments.submit({}, str(uuid4()), retry_of=second)

    # Fails again, then a bar in range is corrected: the retry is refused.
    calls.clear()
    third = env.experiments.submit(request(name="又一次"), str(uuid4()))
    assert env.jobs.wait_until_idle(60)
    bars = market_tables.daily_bars
    with env.engine.begin() as con:
        con.execute(update(bars).where(bars.c.code == CODES[0], bars.c.date == S[50]).values(close=Decimal("1")))
    fourth = env.experiments.submit({}, str(uuid4()), retry_of=third)
    assert env.jobs.wait_until_idle(60)
    refused = env.experiments.get(fourth)
    assert refused["status"] == "failed" and "已变化" in refused["error"]
    assert refused["input_fingerprint"] is None


def test_restart_fails_unfinished_experiments(env):
    found = run(env)
    with env.engine.begin() as con:
        con.execute(update(db.experiments).where(db.experiments.c.id == found["id"]).values(status="running"))
    env.experiments.recover()
    after = env.experiments.get(found["id"])
    assert after["status"] == "failed" and "服务中断" in after["error"]


REFUSED = [
    ({"actions": ["disposition", "priority", "target_weight"]}, "目标权重"),
    ({"actions": ["disposition", "priority", "gross_exposure"]}, "总敞口"),
    ({"actions": ["disposition"]}, "必须声明"),
    ({"trainer": "xgboost"}, "没有这个训练器"),
    ({"trainer_params": {"depth": 3}}, "没有这些参数"),
    ({"test_from": "2026-05-23"}, "不是已知开市日"),
    ({"test_from": S[20].isoformat()}, "还差"),
    ({"test_to": S[90].isoformat()}, "不能晚于"),
    ({"test_to": (S[139] + timedelta(days=1)).isoformat()}, "TOPIX"),  # a session the data has not reached
    ({"baselines": []}, "规则基线"),
    ({"max_weight": 0}, "单只上限"),
    ({"stress_slippages": [0.2]}, "压力场景滑点"),
    ({"source_account_id": 999}, "来源账户不存在"),
    ({"bogus": 1}, "不认识"),
]


def test_a_contract_that_cannot_run_is_refused_and_leaves_nothing(env):
    for changes, match in REFUSED:
        with pytest.raises((ValueError, LookupError), match=match):
            env.experiments.submit(request(**changes), str(uuid4()))
    assert env.experiments.history()["total"] == 0
    assert env.jobs.current() is None


def test_a_source_account_lends_its_capital_rules_and_costs_and_nothing_else(env):
    accounts = Accounts(env.engine, env.market, build_strategy=lambda name, params: Script({}))
    rules = PortfolioRules(max_positions=4, max_weight=Decimal("0.2"), cash_floor=Decimal("0.1"))
    costs = Costs(commission_rate=Decimal("0.001"), commission_min=Decimal("100"), slippage=Decimal("0.002"))
    source = accounts.create(AccountSpec("来源", "script", S[1], initial_cash=Decimal("5000000"), rules=rules,
                                         costs=costs))
    with env.engine.connect() as con:
        before = con.execute(select(account_tables.paper_accounts)).all()
    with pytest.raises(ValueError, match="不能另填"):
        env.experiments.submit({**request(), "source_account_id": source}, str(uuid4()))
    changes = {key: None for key in ("max_positions", "max_weight")}
    found = run(env, source_account_id=source, **changes)
    contract = found["contract"]
    assert contract["source_account_id"] == source
    assert contract["portfolio_rules"] == {"initial_cash": "5000000", "max_positions": 4, "max_weight": "0.2",
                                           "cash_floor": "0.1", "max_adv20_fraction": "0.05"}
    assert contract["costs"] == {"commission_rate": "0.001", "commission_min": "100", "slippage": "0.002"}
    assert found["report"]["replays"][0]["metrics"]["fees"] >= 100
    with env.engine.connect() as con:
        assert con.execute(select(account_tables.paper_accounts)).all() == before
        assert con.execute(select(func.count()).select_from(account_tables.paper_orders)).scalar_one() == 0


def test_history_seen_before_registration_marks_folds_exploratory(env):
    accounts = Accounts(env.engine, env.market, build_strategy=lambda name, params: Script(
        {S[1]: {CODES[0]: Disposition.HOLD}}))
    account = accounts.create(AccountSpec("看过", "script", S[1]))
    accounts.advance(account, through=S[112])
    assert env.experiments.viewed_through() == S[112]
    partly = run(env)
    assert partly["contract"]["viewed_through"] == S[112].isoformat()
    assert [f["viewed"] for f in partly["report"]["folds"]] == [True, True, False]
    assert partly["report"]["evidence"]["reasons"][0]["code"] == "history_partly_viewed"
    # The first experiment's test span has been seen by the second.
    wholly = run(env, name="再来一次")
    assert wholly["contract"]["viewed_through"] == TEST_TO.isoformat()
    assert [f["viewed"] for f in wholly["report"]["folds"]] == [True] * 3
    assert wholly["report"]["evidence"]["reasons"][0]["code"] == "history_viewed"
    assert wholly["report"]["evidence"]["status"] == "exploratory"


def test_too_few_trades_and_zero_trades_are_told_apart(env):
    few = run(env, min_trades=1000)
    assert "too_few_trades" in {r["code"] for r in few["report"]["evidence"]["reasons"]}
    assert few["report"]["evidence"]["status"] == "insufficient_evidence"
    none = run(env, initial_cash=1000)  # not a lot of anything
    codes = {r["code"] for r in none["report"]["evidence"]["reasons"]}
    assert "zero_trades" in codes and "too_few_trades" not in codes
    assert none["report"]["replays"][0]["metrics"]["fill_rate"]["skipped_reasons"]["lot_unaffordable"] > 0


def test_the_adv20_cap_cuts_buys_from_a_whole_turnover_window(env):
    """¥10bn a day: ADV20 is ¥10bn on every test day — the frame reaches 91
    sessions back — so a 0.01% cap is ¥1m, a third of each ¥3m position."""
    found = run(env, max_adv20_fraction=0.0001)
    buys = [o for o in all_orders(env.experiments, found["id"]) if o["kind"] == "buy" and o["status"] == "filled"]
    assert buys and all(o["reason"].get("capped") == "adv20" for o in buys)
    assert all(o["planned_quantity"] * o["fill_price"] <= 1_000_000 * 1.001 for o in buys)
    first = all_days(env.experiments, found["id"])[0]
    assert first["constraints"]["adv20_capped"] == 3
    usage = found["report"]["replays"][0]["metrics"]["adv20"]
    # Sells are not capped: one that gained since its buy can come out over.
    assert usage["cap"] == 0.0001 and usage["median"] <= 0.0001 and usage["without_adv20"] == 0
    assert usage["orders"] == found["report"]["replays"][0]["metrics"]["trades"]


def test_a_request_key_gives_one_experiment_and_refuses_other_terms(env):
    key = str(uuid4())
    first = env.experiments.submit(request(), key)
    assert env.experiments.submit(request(), key) == first
    assert env.jobs.wait_until_idle(60)
    assert env.experiments.submit(request(), key) == first
    with pytest.raises(ValueError, match="请求标识"):
        env.experiments.submit(request(name="别的"), key)
    assert env.experiments.history()["total"] == 1
    summary = env.experiments.history()["experiments"][0]
    assert (summary["id"], summary["evidence_status"], summary["trainer"], summary["test_from"]) == (
        first, "exploratory", "ridge_v1", TEST_FROM.isoformat())
