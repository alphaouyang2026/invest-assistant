"""Model experiments (模型实验, ticket 06a): durable jobs that train, score
out of fold, replay and report under one frozen contract.

An experiment is accepted as one job under the shared writer lock, like a
research run: its contract is frozen and validated inside the lock, then
the job reads the data — the same scope and research input fingerprint as
a research run, over everything it reads — works out the features and
labels, cuts the folds, scores out of fold with the model — choosing its
parameters fold by fold on a validation stretch when it tries more than
one set (ticket 06b) — and each comparison model, keeps the decision days'
scores, and replays them through score
top-N with `replay_range`, the paper accounts' own trading day by day: the
model at the base costs and each stress scenario (the base slippage plus
its addition), each comparison model at the base costs — every replay with its
day-by-day decisions. What it read and when is noted as soon as it has read
it (`reads`); the rest is written only when the whole of it is done, all
at once.

Trainers come from the `trainers` factory (`build_trainer` by default), so
a test swaps the learner without touching the folds, replays or report. A
failure is kept with its kind (`error_code`): data missing, the input
changed since the first attempt, a restart cutting it off, or any other
error. A retry is a new experiment with the same contract, refused once
the input fingerprint differs from the earliest attempt's.
"""
from __future__ import annotations

import hashlib
import resource
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import date
from time import perf_counter
from typing import Any, Literal

import pandas as pd
from sqlalchemy import func, insert, select, update

from app.accounts.accounts import Prices, trading_terms
from app.accounts import experiment_inputs
from app.accounts.records import BUY, FILLED, SELL, record_json
from app.accounts.replay import replay_range
from app.research_jobs import (
    COMPLETED, FAILED, QUEUED, RUNNING, UNFINISHED, code_version, find_request, now, plain_json, submit_once,
)
from app.experiments import contract as contracts
from app.experiments import tables as db
from app.experiments.contract import BASE, MAIN, ExperimentModel
from app.experiments.decisions import Recorded, day_records
from app.experiments.features import feature_table, labels, within_universe
from app.experiments.oof import Search, out_of_fold
from app.experiments.reads import data_read
from app.experiments.report import (
    eligible_equal_weight, evidence, kept_scores, labels_by_day, prediction_diagnostics, replay_figures, score_table,
    TOPIX_BASIS,
)
from app.experiments.trainers import Trainer, build_trainer
from app.jobs import Job, JobOutcome, Progress
from app.market_data import EXEC_CLOSE, TOPIX, UniverseRule
from app.strategies import ScoreTopN

PROGRESS_EVERY = 20  # sessions between stored progress updates in a replay
# What kind of failure stopped an attempt (`error_code`): the data were not all
# there, the input changed since the first attempt, a restart cut it off, or
# any other error.
FailureKind = Literal["missing_data", "input_changed", "interrupted", "error"]
MISSING_DATA: FailureKind = "missing_data"
INPUT_CHANGED: FailureKind = "input_changed"
INTERRUPTED: FailureKind = "interrupted"
ERROR: FailureKind = "error"


class MissingData(ValueError):
    """Data the experiment needs are not held: a failure of its own kind,
    put right by syncing, not by changing the contract."""

    code: FailureKind = MISSING_DATA


class InputChanged(ValueError):
    """A retry's input differs from the first attempt's."""

    code: FailureKind = INPUT_CHANGED


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
                status=FAILED, error="服务中断，实验未完成；请显式重试（将创建新实验）", error_code=INTERRUPTED,
                finished_at=now()))

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
                    contract_hash=contracts.contract_hash(contract), retry_of=retry_of, status=QUEUED,
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
        return contracts.freeze(request, sessions=self._market.calendar().sessions(), source=source,
                                viewed_through=self.viewed_through(), trainers=self._trainers)

    def viewed_through(self) -> date | None:
        """The latest session whose results could have been seen by now:
        paper accounts, completed research runs and completed experiments'
        test spans."""
        seen = [experiment_inputs.viewed_through(self._engine), self._latest_experiment_end()]
        return max((day for day in seen if day is not None), default=None)

    def validate(self, contract: Mapping[str, Any]) -> contracts.ExperimentPlan:
        """Whether `contract` can run on the data held now — the folds' history,
        its trainers, TOPIX over the test span, the session after it;
        ValueError naming why not (MissingData for data not held yet).
        Cheap: the calendar and one TOPIX read."""
        calendar = self._market.calendar()
        plan = contracts.plan(contract, calendar.sessions())
        for model in contracts.models(contract):
            self._trainers(model.trainer, model.params)
        values = self._market.read([TOPIX], plan.test_days[0], plan.test_days[-1]).wide(EXEC_CLOSE)
        values = values.reindex(plan.test_days)
        closes = values[TOPIX] if TOPIX in values else [None] * len(plan.test_days)
        missing = [day.isoformat() for day, close in zip(plan.test_days, closes) if pd.isna(close) or close <= 0]
        if missing:
            raise MissingData(f"缺数据：测试区间 {plan.test_days[0]} 至 {plan.test_days[-1]} 有 {len(missing)} 个开市日的"
                              f" TOPIX 收盘缺失或无效（{_first_days(missing)}），补齐行情后可以重试")
        try:
            calendar.next(plan.test_days[-1])
        except LookupError:
            raise MissingData("缺数据：测试终点后缺少开市日历，无法记录末日待执行订单，请先同步日历") from None
        return plan

    # --- the job -------------------------------------------------------------

    def execute(self, experiment_id: str, progress: Progress, *,
                expect_fingerprint: str | None = None) -> JobOutcome:
        """Run one queued experiment, inside a job. With `expect_fingerprint`,
        refuse once the research input fingerprint differs from it (a
        retry). Records a failure, and its kind, on the experiment, then
        raises."""
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
            missing = fingerprint["missing_stock_sessions"]
            if missing:
                raise MissingData(f"缺数据：实验读取区间 {plan.read_from} 至 {last} 有 {len(missing)} 个开市日没有股票日线"
                                  f"（{_first_days(missing)}），补齐行情后可以重试")
            if expect_fingerprint is not None and fingerprint["sha256"] != expect_fingerprint:
                raise InputChanged("该实验读取区间的行情自首次尝试后已变化，不能按原契约重试，请登记新实验")
            self._set(experiment_id, input_fingerprint=fingerprint)
            timings["fingerprint"] = perf_counter() - started

            step({"stage": "reading"})
            mark = perf_counter()
            observed_at = now()
            universes = self._market.universe(first, last, rule=UniverseRule(contract["universe_rule"]))
            codes = sorted({code for listed in universes.values() for code in listed})
            frame = self._market.read(codes, plan.read_from, last)
            topix = self._market.read([TOPIX], plan.test_days[0], last).wide(EXEC_CLOSE)[TOPIX]
            sessions = calendar.sessions()
            self._set(experiment_id, data_read=data_read(
                observed_at=observed_at, fingerprint=fingerprint, frame=frame, universes=universes, topix=topix,
                calendar=[day for day in sessions if plan.read_from <= day <= last] + [calendar.next(last)]))
            timings["reading"] = perf_counter() - mark

            step({"stage": "features"})
            mark = perf_counter()
            features = within_universe(feature_table(frame, plan.feature_days), universes)
            targets = within_universe(labels(frame, plan.feature_days, contract["task"]["horizon"]), universes)
            timings["features"] = perf_counter() - mark

            models = contracts.models(contract)
            oofs, kept = {}, {}
            timings["training"] = {}
            for model in models:
                step({"stage": "training", "model": model.key, "label": model.label, "trainer": model.trainer})
                mark = perf_counter()
                trainer = self._trainers(model.trainer, model.params)
                if model.search:
                    trainer = Search([self._trainers(model.trainer, params) for params in model.search["grid"]],
                                     model.search["validation_sessions"], model.search["top_n"])
                oofs[model.key] = out_of_fold(trainer, plan.folds, features, targets, sessions=plan.sessions,
                                              label_sessions=contract["task"]["label_sessions"])
                kept[model.key] = kept_scores(oofs[model.key].scores, plan.decision_days)
                timings["training"][model.key] = perf_counter() - mark

            prices = Prices(frame)
            rules, base, initial = trading_terms(contract)
            planned = contracts.replays(contract)
            policy = {name: contract["policy"][name] for name in ("max_holding_sessions", "warmup_sessions")}
            replays, timings["replays"] = [], []
            for run in planned:
                mark = perf_counter()
                key = run.model.key
                costs = base if run.scenario == BASE else replace(base, slippage=run.slippage)
                strategy = Recorded(ScoreTopN(score_table(kept[key], plan.decision_days), policy))

                def on_session(done: int, day: date, position: int = run.position) -> None:
                    if done % PROGRESS_EVERY == 0 or done == len(plan.test_days):
                        step({"stage": "replaying", "replays_done": position - 1, "replays_total": len(planned),
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
                figures = replay_figures(replay, plan.folds, cap=rules.max_adv20_fraction, adv20=adv20,
                                         closes=prices.closes(last, replay.ledger.positions))
                replays.append({"position": run.position, "model": key, "model_label": run.model.label,
                                "scenario": run.scenario,
                                "extra_bps": None if run.extra_bps is None else float(run.extra_bps),
                                "costs": {name: str(value) for name, value in asdict(costs).items()},
                                "result": figures, "records": replay.ledger.records,
                                "days": day_records(replay, strategy, prices, universes, plan.decision_days,
                                                    kept[key])})
                timings["replays"].append(perf_counter() - mark)

            step({"stage": "reporting"})
            report = self._report(contract, plan, models, oofs, kept, targets, universes, replays)
            timings["total"] = perf_counter() - started
            # The whole process's peak so far, not this job's alone: what the machine had to have.
            timings["peak_memory_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            report["timings"] = timings
            self._store(experiment_id, models, oofs, kept, replays, report)
            return JobOutcome({"experiment_id": experiment_id, "evidence_status": report["evidence"]["status"],
                               "sessions": len(plan.test_days), "seconds": round(timings["total"], 1)},
                              report["warnings"])
        except Exception as error:
            # Only this module's own failures name their kind: another error's
            # `code` (SQLAlchemy's, say) is not a FailureKind.
            kind = error.code if isinstance(error, MissingData | InputChanged) else ERROR
            self._set(experiment_id, status=FAILED, error=str(error), error_code=kind, finished_at=now())
            raise

    def _report(self, contract, plan, models: list[ExperimentModel], oofs, kept, targets, universes,
                replays) -> dict:
        daily = labels_by_day(targets)
        seen_through = contract["viewed_through"] and date.fromisoformat(contract["viewed_through"])
        out_models = []
        for model in models:
            failed = [r.fold.number for r in oofs[model.key].folds if r.failed]
            out_models.append({
                "key": model.key, "role": model.role, "label": model.label, "trainer": model.trainer,
                "params": model.params, "failed_folds": failed,
                "diagnostics": prediction_diagnostics(kept[model.key], daily, universes, plan.decision_days,
                                                      plan.folds, top_n=contract["portfolio_rules"]["max_positions"])})
        main = out_models[0]
        base_metrics = replays[0]["result"]["metrics"]
        minimums = contract["minimums"]
        found = evidence(
            folds=plan.folds, viewed_through=seen_through or None,
            failed={f"{m['label']}（{m['trainer']}）": m["failed_folds"] for m in out_models},
            samples={r.fold.number: r.samples for r in oofs[MAIN].folds},
            min_samples=minimums["training_samples"],
            coverage=main["diagnostics"]["coverage_mean"], min_coverage=minimums["coverage"],
            ic_days=main["diagnostics"]["ic_days"], min_labelled_days=minimums["labelled_days"],
            trades=base_metrics["trades"], min_trades=minimums["trades"])
        return plain_json({
            "contract_hash": contracts.contract_hash(contract),
            "sessions": len(plan.test_days), "decision_days": len(plan.decision_days),
            "read_from": plan.read_from.isoformat(),
            "folds": [{"number": fold.number, **_fold(fold), "viewed": fold.number in found["viewed_folds"]}
                      for fold in plan.folds],
            "models": out_models,
            "benchmarks": {
                "topix_price": {"basis": TOPIX_BASIS, "total_return": base_metrics["topix_return"]},
                "eligible_equal_weight": eligible_equal_weight(daily, universes, plan.decision_days),
            },
            "stress_basis": contracts.STRESS_BASIS,
            "replays": [{key: r[key] for key in ("position", "model", "model_label", "scenario", "extra_bps",
                                                 "costs")}
                        | {key: r["result"][key] for key in ("metrics", "folds", "years")} for r in replays],
            "evidence": found,
            "warnings": sorted({w for r in replays for w in r["result"]["warnings"]}),
        })

    def _store(self, experiment_id, models: list[ExperimentModel], oofs, kept, replays, report) -> None:
        folds = [{"experiment_id": experiment_id, "model": model.key, "fold": r.fold.number, **_fold(r.fold),
                  "samples": r.samples, "seconds": r.seconds,
                  "artifact": None if r.artifact is None else r.artifact.as_dict(),
                  "artifact_hash": None if r.artifact is None else r.artifact.hash(), "error": r.error,
                  "search": r.search}
                 for model in models for r in oofs[model.key].folds]
        scores = [{"experiment_id": experiment_id, "model": model.key, "as_of": day.isoformat(), **entry}
                  for model in models for day, entry in kept[model.key].items()]
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
                                                     "sequence": record.id, "record": record_json(record)}
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
            completed = con.execute(select(db.experiments.c.contract)
                                    .where(db.experiments.c.status == COMPLETED)).scalars().all()
        return max((date.fromisoformat(c["test_to"]) for c in completed), default=None)

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
        experiment["fold_results"] = [  # the model's first
            {**{k: v for k, v in f.items() if k != "experiment_id"}, "artifact": _brief(f["artifact"])}
            for f in sorted(folds, key=lambda f: (f["model"] != MAIN, f["model"], f["fold"]))]
        return experiment

    def artifact(self, experiment_id: str, model: str, fold: int) -> dict:
        """One fold's model artifact whole, as stored — `get` shortens its
        long parts (a ranker's booster)."""
        f = db.folds
        with self._engine.connect() as con:
            found = con.execute(select(f.c.artifact).where(
                f.c.experiment_id == experiment_id, f.c.model == model, f.c.fold == fold)).one_or_none()
        if found is None:
            raise LookupError("没有这一折")
        if found.artifact is None:
            raise LookupError("这一折训练失败，没有模型工件")
        return found.artifact

    def history(self, page: int = 1, page_size: int = 20) -> dict:
        e = db.experiments
        columns = [e.c.id, e.c.contract, e.c.contract_hash, e.c.retry_of, e.c.status, e.c.created_at,
                   e.c.finished_at, e.c.error, e.c.error_code, e.c.evidence_status]
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
        """One replay's days, oldest first — a stress scenario's as much as
        the base's; each decision day with the model's best scores that day."""
        replay = self._replay_row(experiment_id, position, columns=("model",))
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


def _first_days(days: list[str]) -> str:
    """The first five of `days` a missing-data failure names, and "……" if there are more."""
    return "、".join(days[:5]) + ("……" if len(days) > 5 else "")


def _ranked(scores: Mapping[str, float]) -> list[dict]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [{"code": code, "score": score, "rank": n} for n, (code, score) in enumerate(ordered, 1)]


ARTIFACT_INLINE = 4096  # characters of an artifact's state value shown in the detail; longer ones are named only


def _brief(artifact: dict | None) -> dict | None:
    """An artifact with each long text in its state (a ranker's booster)
    replaced by its length and sha256 — the whole is one request away."""
    if artifact is None:
        return None
    state = {key: {"omitted": True, "characters": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}
             if isinstance(value, str) and len(value) > ARTIFACT_INLINE else value
             for key, value in artifact["state"].items()}
    return {**artifact, "state": state}


def _fold(fold) -> dict:
    return {"train_from": fold.train_from.isoformat(), "train_to": fold.train_to.isoformat(),
            "test_from": fold.test_from.isoformat(), "test_to": fold.test_to.isoformat()}


