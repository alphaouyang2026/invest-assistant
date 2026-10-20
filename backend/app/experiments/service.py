"""Model experiments (模型实验, ticket 06a): durable jobs that train, score
out of fold, replay and report under one frozen contract.

An experiment is accepted as one job under the shared writer lock, like a
research run: its contract is frozen and validated inside the lock, then
the job reads the data — the same scope and research input fingerprint as
a research run, over everything it reads — works out the features and
labels, cuts the folds, scores out of fold with the model and each rule
baseline, keeps the decision days' scores, and replays them through score
top-N with `replay_range`, the paper accounts' own trading day by day: the
model at the base costs and each stress scenario, each baseline at the base
costs. Nothing is written until the whole of it is done, then all at once.

Trainers come from the `trainers` factory (`build_trainer` by default), so
a test swaps the learner without touching the folds, replays or report. A
restart fails what was left unfinished; a retry is a new experiment with
the same contract, refused once the input fingerprint differs from the
earliest attempt's.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any

import pandas as pd
from sqlalchemy import func, insert, select, update

from app.accounts.accounts import Prices, trading_terms
from app.accounts import experiment_inputs
from app.accounts.records import BUY, FILLED, SELL
from app.accounts.replay import replay_range
from app.accounts.research_jobs import (
    COMPLETED, FAILED, QUEUED, RUNNING, UNFINISHED, code_version, find_request, now, plain_json, submit_once,
)
from app.experiments import contract as terms
from app.experiments import tables as db
from app.experiments.decisions import Recorded, day_records
from app.experiments.features import feature_table, labels, within_universe
from app.experiments.oof import out_of_fold
from app.experiments.report import (
    eligible_equal_weight, evidence, kept_scores, labels_by_day, prediction_diagnostics, replay_figures, score_table,
    TOPIX_BASIS,
)
from app.experiments.trainers import Trainer, build_trainer
from app.jobs import Job, JobOutcome, Progress
from app.market_data import EXEC_CLOSE, TOPIX, UniverseRule
from app.strategies import ScoreTopN

PROGRESS_EVERY = 20  # sessions between stored progress updates in a replay
MAIN = "model"


class ModelExperiments:
    def __init__(self, engine, market, jobs, *,
                 trainers: Callable[[str, Mapping[str, Any]], Trainer] = build_trainer) -> None:
        self._engine, self._market, self._jobs = engine, market, jobs
        self._trainers = trainers

    # --- accepting work ------------------------------------------------------

    def recover(self) -> None:
        """At start-up; never marks another live process's experiment interrupted."""
        self._jobs.when_idle(self.interrupt_unfinished)

    def interrupt_unfinished(self) -> None:
        """Call under the writer lock: nothing runs then."""
        with self._engine.begin() as con:
            con.execute(update(db.experiments).where(db.experiments.c.status.in_(UNFINISHED)).values(
                status=FAILED, error="服务中断，实验未完成；请显式重试（将创建新实验）", finished_at=now()))

    def submit(self, request: dict, key: str, *, retry_of: str | None = None) -> str:
        """Register `request` (the contract's terms, see `contract.DEFAULTS`)
        or retry the failed experiment `retry_of`; the experiment's id."""
        try:
            request = plain_json(request)
        except ValueError:
            raise ValueError("实验参数必须是有限数值") from None
        if retry_of:
            original = self.get(retry_of)
            if original["status"] != FAILED:
                raise ValueError("只有失败的实验可以重试")
            request = {"retry_of": retry_of}
        experiment_id = uuid.uuid4().hex
        expected: list[str | None] = []

        def prepare() -> None:
            # Jobs holds the cross-process writer lock before invoking prepare.
            self.interrupt_unfinished()
            if retry_of:
                contract = original["contract"]
                expected.append(self._earliest_fingerprint(retry_of))
            else:
                contract = self.freeze(request)
            self.validate(contract)
            with self._engine.begin() as con:
                con.execute(insert(db.experiments).values(
                    id=experiment_id, request_key=key, request=request, contract=contract,
                    contract_hash=terms.contract_hash(contract), retry_of=retry_of, status=QUEUED,
                    created_at=now(), progress={}, code_version=code_version()))

        job = Job("model_experiment", lambda progress: self.execute(
            experiment_id, progress, expect_fingerprint=expected[0] if expected else None))
        return submit_once(self._jobs, job, prepare=prepare,
                           find=lambda: find_request(self._engine, db.experiments, key, request), new_id=experiment_id)

    def freeze(self, request: Mapping[str, Any]) -> dict:
        """The contract `request` registers now: the source's trading terms
        if it names one, and how far history has been seen."""
        source_id = request.get("source_account_id")
        source = None if source_id is None else experiment_inputs.source_terms(self._engine, source_id)
        return terms.freeze(request, sessions=self._market.calendar().sessions(), source=source,
                            viewed_through=self.viewed_through(), trainers=self._trainers)

    def viewed_through(self) -> date | None:
        """The latest session whose results could have been seen by now:
        paper accounts, completed research runs and completed experiments'
        test spans."""
        seen = [experiment_inputs.viewed_through(self._engine), self._latest_experiment_end()]
        return max((day for day in seen if day is not None), default=None)

    def validate(self, contract: Mapping[str, Any]) -> terms.ExperimentPlan:
        """Whether `contract` can run on the data held now — the folds' history,
        its trainers, TOPIX over the test span, the session after it;
        ValueError naming why not. Cheap: the calendar and one TOPIX read."""
        calendar = self._market.calendar()
        plan = terms.plan(contract, calendar.sessions())
        for model in (contract["model"], *contract["baselines"]):
            self._trainers(model["trainer"], model["params"])
        values = self._market.read([TOPIX], plan.test_days[0], plan.test_days[-1]).wide(EXEC_CLOSE)
        values = values.reindex(plan.test_days)
        if TOPIX not in values or any(pd.isna(v) or v <= 0 for v in values[TOPIX]):
            raise ValueError("测试区间 TOPIX 数据缺失或无效，请先补齐行情")
        try:
            calendar.next(plan.test_days[-1])
        except LookupError:
            raise ValueError("测试终点后缺少开市日历，无法记录末日待执行订单，请先同步日历") from None
        return plan

    # --- the job -------------------------------------------------------------

    def execute(self, experiment_id: str, progress: Progress, *,
                expect_fingerprint: str | None = None) -> JobOutcome:
        """Run one queued experiment, inside a job. With `expect_fingerprint`,
        refuse once the research input fingerprint differs from it (a
        retry). Records a failure on the experiment, then raises."""
        started = perf_counter()
        self._set(experiment_id, status=RUNNING)
        try:
            contract = self.get(experiment_id)["contract"]
            plan = self.validate(contract)
            calendar = self._market.calendar()
            step = self._stepper(experiment_id, progress)
            timings: dict[str, Any] = {}
            first, last = plan.feature_days[0], plan.test_days[-1]

            step({"stage": "fingerprint"})
            fingerprint = self._market.input_fingerprint(plan.read_from, last)
            if fingerprint["missing_stock_sessions"]:
                raise ValueError("实验读取区间缺少股票行情：" + ", ".join(fingerprint["missing_stock_sessions"][:5]))
            if expect_fingerprint is not None and fingerprint["sha256"] != expect_fingerprint:
                raise ValueError("该实验读取区间的行情自首次尝试后已变化，不能按原契约重试，请登记新实验")
            self._set(experiment_id, input_fingerprint=fingerprint)
            timings["fingerprint"] = perf_counter() - started

            step({"stage": "reading"})
            mark = perf_counter()
            universes = self._market.universe(first, last, rule=UniverseRule(contract["universe_rule"]))
            codes = sorted({code for listed in universes.values() for code in listed})
            frame = self._market.read(codes, plan.read_from, last)
            timings["reading"] = perf_counter() - mark

            step({"stage": "features"})
            mark = perf_counter()
            features = within_universe(feature_table(frame, plan.feature_days), universes)
            targets = within_universe(labels(frame, plan.feature_days, contract["task"]["horizon"]), universes)
            timings["features"] = perf_counter() - mark

            models = [(MAIN, contract["model"])] + [
                (f"baseline_{n}", baseline) for n, baseline in enumerate(contract["baselines"], 1)]
            oofs, kept = {}, {}
            timings["training"] = {}
            for key, spec in models:
                step({"stage": "training", "model": key})
                mark = perf_counter()
                trainer = self._trainers(spec["trainer"], spec["params"])
                oofs[key] = out_of_fold(trainer, plan.folds, features, targets, sessions=plan.sessions,
                                        label_sessions=contract["task"]["label_sessions"])
                kept[key] = kept_scores(oofs[key].scores, plan.decision_days)
                timings["training"][key] = perf_counter() - mark

            prices = Prices(frame)
            topix = self._market.read([TOPIX], plan.test_days[0], last).wide(EXEC_CLOSE)[TOPIX]
            rules, base, initial = trading_terms(contract)
            runs = [(MAIN, "base", base)] + [(MAIN, "stress", replace(base, slippage=Decimal(s)))
                                             for s in contract["stress_slippages"]]
            runs += [(key, "base", base) for key, _ in models[1:]]
            policy = {name: contract["policy"][name] for name in ("max_holding_sessions", "warmup_sessions")}
            replays, timings["replays"] = [], []
            for position, (key, scenario, costs) in enumerate(runs, 1):
                mark = perf_counter()
                strategy = Recorded(ScoreTopN(score_table(kept[key], plan.decision_days), policy))

                def on_session(done: int, day: date, position: int = position) -> None:
                    if done % PROGRESS_EVERY == 0 or done == len(plan.test_days):
                        step({"stage": "replaying", "replays_done": position - 1, "replays_total": len(runs),
                              "sessions_done": done, "sessions_total": len(plan.test_days),
                              "current_session": day.isoformat()})

                replay = replay_range(prices, strategy, universes, plan.test_days, calendar, rules, costs, initial,
                                      topix, on_session=on_session)
                filled = [r for r in replay.ledger.records if r.kind in (BUY, SELL) and r.status == FILLED]
                adv20 = {}
                for r in filled:
                    found = prices.adv20(r.signal_date, [r.code]).get(r.code)
                    if found is not None:
                        adv20[(r.signal_date, r.code)] = found
                figures = replay_figures(replay, initial, plan.folds, cap=rules.max_adv20_fraction, adv20=adv20,
                                         closes=prices.closes(last, replay.ledger.positions))
                figures["pending"] = [_record(r) for r in replay.ledger.pending]
                replays.append({"position": position, "model": key, "scenario": scenario,
                                "costs": {name: str(value) for name, value in asdict(costs).items()},
                                "result": figures, "records": replay.ledger.records,
                                # A stress replay differs from its base only in costs: its ledger and
                                # NAV are kept, its day-by-day decisions are not.
                                "days": [] if scenario == "stress" else day_records(
                                    replay, strategy, prices, universes, plan.test_days, plan.decision_days,
                                    kept[key])})
                timings["replays"].append(perf_counter() - mark)

            step({"stage": "reporting"})
            report = self._report(contract, plan, models, oofs, kept, targets, universes, replays)
            timings["total"] = perf_counter() - started
            report["timings"] = timings
            self._store(experiment_id, models, oofs, kept, replays, report)
            return JobOutcome({"experiment_id": experiment_id, "evidence_status": report["evidence"]["status"],
                               "sessions": len(plan.test_days), "seconds": round(timings["total"], 1)},
                              report["warnings"])
        except Exception as error:
            self._set(experiment_id, status=FAILED, error=str(error), finished_at=now())
            raise

    def _report(self, contract, plan, models, oofs, kept, targets, universes, replays) -> dict:
        daily = labels_by_day(targets)
        seen_through = contract["viewed_through"] and date.fromisoformat(contract["viewed_through"])
        out_models = []
        for key, spec in models:
            failed = [r.fold.number for r in oofs[key].folds if r.failed]
            out_models.append({
                "key": key, "role": "model" if key == MAIN else "baseline", "trainer": spec["trainer"],
                "params": spec["params"], "failed_folds": failed,
                "diagnostics": prediction_diagnostics(kept[key], daily, universes, plan.decision_days, plan.folds)})
        main = out_models[0]
        base_metrics = replays[0]["result"]["metrics"]
        found = evidence(
            folds=plan.folds, viewed_through=seen_through or None,
            failed={_model_label(m): m["failed_folds"] for m in out_models},
            coverage=main["diagnostics"]["coverage_mean"], min_coverage=contract["minimums"]["coverage"],
            ic_days=main["diagnostics"]["ic_days"], trades=base_metrics["trades"],
            min_trades=contract["minimums"]["trades"])
        return plain_json({
            "contract_hash": terms.contract_hash(contract),
            "sessions": len(plan.test_days), "decision_days": len(plan.decision_days),
            "read_from": plan.read_from.isoformat(),
            "folds": [{"number": fold.number, **_fold(fold), "viewed": fold.number in found["viewed_folds"]}
                      for fold in plan.folds],
            "models": out_models,
            "benchmarks": {
                "topix_price": {"basis": TOPIX_BASIS, "total_return": base_metrics["topix_return"]},
                "eligible_equal_weight": eligible_equal_weight(daily, universes, plan.decision_days),
            },
            "replays": [{"position": r["position"], "model": r["model"], "scenario": r["scenario"],
                         "costs": r["costs"], **{k: r["result"][k] for k in ("metrics", "folds", "years")}}
                        for r in replays],
            "evidence": found,
            "warnings": sorted({w for r in replays for w in r["result"]["warnings"]}),
        })

    def _store(self, experiment_id, models, oofs, kept, replays, report) -> None:
        folds = [{"experiment_id": experiment_id, "model": key, "fold": r.fold.number, **_fold(r.fold),
                  "samples": r.samples, "seconds": r.seconds,
                  "artifact": None if r.artifact is None else r.artifact.as_dict(),
                  "artifact_hash": None if r.artifact is None else r.artifact.hash(), "error": r.error}
                 for key, _ in models for r in oofs[key].folds]
        scores = [{"experiment_id": experiment_id, "model": key, "as_of": day.isoformat(), **entry}
                  for key, _ in models for day, entry in kept[key].items()]
        with self._engine.begin() as con:
            con.execute(insert(db.folds), plain_json(folds))
            if scores:
                con.execute(insert(db.scores), scores)
            for r in replays:
                con.execute(insert(db.replays).values(
                    experiment_id=experiment_id, position=r["position"], model=r["model"], scenario=r["scenario"],
                    costs=r["costs"], result=plain_json(r["result"])))
                if r["records"]:
                    con.execute(insert(db.orders), [{"experiment_id": experiment_id, "position": r["position"],
                                                     "sequence": record.id, "record": _record(record)}
                                                    for record in r["records"]])
                if r["days"]:
                    con.execute(insert(db.days), [{"experiment_id": experiment_id, "position": r["position"],
                                                   "day": d["date"], "decision_day": d["decision_day"],
                                                   "record": plain_json(d)} for d in r["days"]])
            con.execute(update(db.experiments).where(db.experiments.c.id == experiment_id).values(
                status=COMPLETED, report=report, evidence_status=report["evidence"]["status"], finished_at=now()))

    def _stepper(self, experiment_id: str, progress: Progress) -> Progress:
        def step(values: dict[str, Any]) -> None:
            self._set(experiment_id, progress=values)
            progress(values)
        return step

    def _set(self, experiment_id: str, **values: Any) -> None:
        with self._engine.begin() as con:
            con.execute(update(db.experiments).where(db.experiments.c.id == experiment_id).values(**values))

    def _earliest_fingerprint(self, experiment_id: str) -> str | None:
        """Along the chain of attempts back from `experiment_id`, the oldest
        input fingerprint stored: only an attempt whose input was accepted
        has one."""
        found, current = None, experiment_id
        while current:
            with self._engine.connect() as con:
                row = con.execute(select(db.experiments.c.retry_of, db.experiments.c.input_fingerprint)
                                  .where(db.experiments.c.id == current)).one()
            if row.input_fingerprint:
                found = row.input_fingerprint["sha256"]
            current = row.retry_of
        return found

    def _latest_experiment_end(self) -> date | None:
        with self._engine.connect() as con:
            contracts = con.execute(select(db.experiments.c.contract)
                                    .where(db.experiments.c.status == COMPLETED)).scalars().all()
        return max((date.fromisoformat(c["test_to"]) for c in contracts), default=None)

    # --- reading -------------------------------------------------------------

    def get(self, experiment_id: str) -> dict:
        e = db.experiments
        columns = [c for c in e.c if c.name not in ("request", "request_key")]
        with self._engine.connect() as con:
            row = con.execute(select(*columns).where(e.c.id == experiment_id)).mappings().one_or_none()
            if row is None:
                raise LookupError("模型实验不存在")
            folds = con.execute(select(db.folds).where(db.folds.c.experiment_id == experiment_id)
                                .order_by(db.folds.c.model, db.folds.c.fold)).mappings().all()
            retried_by = con.execute(select(e.c.id).where(e.c.retry_of == experiment_id)
                                     .order_by(e.c.created_at, e.c.id)).scalars().all()
        experiment = dict(row)
        experiment["name"] = experiment["contract"]["name"]
        experiment["retried_by"] = list(retried_by)
        experiment["fold_results"] = [{k: v for k, v in f.items() if k != "experiment_id"}  # the model's first
                                      for f in sorted(folds, key=lambda f: (f["model"] != MAIN, f["model"], f["fold"]))]
        return experiment

    def history(self, page: int = 1, page_size: int = 20) -> dict:
        e = db.experiments
        columns = [e.c.id, e.c.contract, e.c.contract_hash, e.c.retry_of, e.c.status, e.c.created_at,
                   e.c.finished_at, e.c.error, e.c.evidence_status]
        with self._engine.connect() as con:
            total = con.execute(select(func.count()).select_from(e)).scalar_one()
            rows = con.execute(select(*columns).order_by(e.c.created_at.desc(), e.c.id)
                               .offset((page - 1) * page_size).limit(page_size)).mappings().all()
        experiments = []
        for row in rows:
            contract = row["contract"]
            experiments.append({
                **{k: v for k, v in row.items() if k != "contract"}, "name": contract["name"],
                "test_from": contract["test_from"], "test_to": contract["test_to"],
                "trainer": contract["model"]["trainer"], "baselines": [b["trainer"] for b in contract["baselines"]],
                "source_account_id": contract["source_account_id"]})
        return {"total": total, "page": page, "page_size": page_size, "experiments": experiments}

    def replay(self, experiment_id: str, position: int) -> dict:
        return {k: v for k, v in self._replay_row(experiment_id, position).items() if k != "experiment_id"}

    def orders(self, experiment_id: str, position: int, page: int = 1, page_size: int = 50) -> dict:
        """One replay's ledger, newest first."""
        self._replay_row(experiment_id, position, columns=("position",))
        o = db.orders
        where = (o.c.experiment_id == experiment_id) & (o.c.position == position)
        with self._engine.connect() as con:
            total = con.execute(select(func.count()).select_from(o).where(where)).scalar_one()
            records = con.execute(select(o.c.record).where(where).order_by(o.c.sequence.desc())
                                  .offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size, "orders": records}

    def days(self, experiment_id: str, position: int, page: int = 1, page_size: int = 20, *,
             decision_only: bool = False) -> dict:
        """One replay's days, oldest first; each decision day with the
        model's best scores that day. A stress replay keeps none."""
        replay = self._replay_row(experiment_id, position, columns=("model", "scenario"))
        if replay["scenario"] == "stress":
            raise LookupError("压力场景回放只保存订单和净值，逐日决定请看同一模型的基础成本回放")
        contract = self.get_contract(experiment_id)
        top = max(20, 2 * contract["portfolio_rules"]["max_positions"])
        d = db.days
        where = (d.c.experiment_id == experiment_id) & (d.c.position == position)
        if decision_only:
            where &= d.c.decision_day.is_(True)
        with self._engine.connect() as con:
            total = con.execute(select(func.count()).select_from(d).where(where)).scalar_one()
            records = con.execute(select(d.c.record).where(where).order_by(d.c.day)
                                  .offset((page - 1) * page_size).limit(page_size)).scalars().all()
            wanted = [r["date"] for r in records if r["decision_day"]]
            s = db.scores
            kept = dict(con.execute(select(s.c.as_of, s.c.scores).where(
                s.c.experiment_id == experiment_id, s.c.model == replay["model"], s.c.as_of.in_(wanted))).all())
        for record in records:
            record["top_scores"] = _ranked(kept.get(record["date"], {}))[:top]
        return {"total": total, "page": page, "page_size": page_size, "days": records}

    def scores(self, experiment_id: str, model: str, day: date) -> dict:
        """Every score one model gave on one decision day, best first."""
        self.get_contract(experiment_id)
        s = db.scores
        with self._engine.connect() as con:
            row = con.execute(select(s).where(s.c.experiment_id == experiment_id, s.c.model == model,
                                              s.c.as_of == day.isoformat())).mappings().one_or_none()
        if row is None:
            raise LookupError("这一天没有该模型的分数（不是决策日，或该折失败）")
        return {"model": model, "as_of": row["as_of"], "fold": row["fold"], "artifact_hash": row["artifact_hash"],
                "scores": _ranked(row["scores"])}

    def get_contract(self, experiment_id: str) -> dict:
        with self._engine.connect() as con:
            contract = con.execute(select(db.experiments.c.contract)
                                   .where(db.experiments.c.id == experiment_id)).scalar_one_or_none()
        if contract is None:
            raise LookupError("模型实验不存在")
        return contract

    def _replay_row(self, experiment_id: str, position: int, columns: tuple[str, ...] | None = None) -> dict:
        self.get_contract(experiment_id)
        r = db.replays
        selected = [r.c[name] for name in columns] if columns else [r]
        with self._engine.connect() as con:
            row = con.execute(select(*selected).where(r.c.experiment_id == experiment_id, r.c.position == position)
                              ).mappings().one_or_none()
        if row is None:
            raise LookupError(f"该实验没有第 {position} 个回放（实验未完成，或编号不对）")
        return dict(row)


def _ranked(scores: Mapping[str, float]) -> list[dict]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [{"code": code, "score": score, "rank": n} for n, (code, score) in enumerate(ordered, 1)]


def _fold(fold) -> dict:
    return {"train_from": fold.train_from.isoformat(), "train_to": fold.train_to.isoformat(),
            "test_from": fold.test_from.isoformat(), "test_to": fold.test_to.isoformat()}


def _model_label(model: Mapping[str, Any]) -> str:
    return f"{'主模型' if model['role'] == 'model' else '规则基线'} {model['trainer']}"


def _record(record) -> dict:
    return {**plain_json(asdict(record)), "name": None, "fees": float(record.fees),
            "fill_price": None if record.fill_price is None else float(record.fill_price),
            "cash_delta": float(record.cash_delta)}
