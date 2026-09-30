"""Research batches: one fixed configuration over several ranges (04b-B).

Every attempt at a segment is an ordinary research run, replayed by
`ResearchRuns.execute` with the source's capital and no holdings — there is no
second replay engine. A batch runs all its segments in one job, under the
shared writer lock, so they read one data state. Statuses are not stored:
a segment's is its latest attempt's run status, the batch's follows from them.
"""
from __future__ import annotations

import statistics
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import Engine, func, insert, select

from app.accounts import research_tables as db
from app.accounts.research import ResearchRuns
from app.accounts.research_jobs import (
    COMPLETED, FAILED, QUEUED, RUNNING, UNFINISHED, KEY_REUSED, RunStatus, code_version, find_request, now,
    plain_json, submit_once,
)
from app.jobs import Job, JobOutcome, Jobs, Progress

MAX_BATCH_RUNS = 20
PARTIAL = "partial"
BatchStatus = Literal[RunStatus, "partial"]


class StaleInput(Exception):
    """The market data changed since the ranges were chosen."""


@dataclass(frozen=True)
class SegmentSpec:
    start: date
    end: date
    interval_id: int | None = None


class ResearchBatches:
    def __init__(self, engine: Engine, runs: ResearchRuns, jobs: Jobs) -> None:
        self._engine, self._runs, self._jobs = engine, runs, jobs

    def submit(self, *, source_account_id: int, entry_above: float, exit_below: float,
               segments: Sequence[SegmentSpec], key: str, discovery_id: str | None = None,
               selection: dict | None = None, classification_fingerprint: dict | None = None,
               precheck: Callable[[], None] | None = None) -> str:
        """Accept one configuration over `segments`, or reject it whole: a
        segment that cannot run is named, never silently dropped.
        `classification_fingerprint` is the discovery's, kept as a record;
        `precheck` (run under the writer lock) is what enforces it."""
        segments = list(segments)
        if not segments:
            raise ValueError("请至少选择一段区间")
        if len(segments) > MAX_BATCH_RUNS:
            raise ValueError(f"所选 {len(segments)} 段超过单批上限 {MAX_BATCH_RUNS}，请减少勾选")
        try:
            request = plain_json({
                "source_account_id": source_account_id, "entry_above": entry_above, "exit_below": exit_below,
                "discovery_id": discovery_id,
                "segments": [{"start_date": s.start.isoformat(), "end_date": s.end.isoformat(),
                              "interval_id": s.interval_id} for s in segments],
            })
        except ValueError:
            raise ValueError("策略参数必须是有限数值") from None
        batch_id = uuid.uuid4().hex
        run_ids: list[str] = []

        def prepare() -> None:
            # Jobs holds the cross-process writer lock before invoking prepare.
            self._runs.interrupt_unfinished()
            if precheck is not None:
                precheck()
            config = self._runs.frozen_config(source_account_id, entry_above, exit_below, None, None)
            base = {k: v for k, v in config.items() if k not in ("start_date", "end_date")}
            configs, problems = [], []
            for s in request["segments"]:
                segment_config = {**base, "start_date": s["start_date"], "end_date": s["end_date"]}
                try:
                    self._runs.validate(segment_config)
                except ValueError as error:
                    problems.append(f"{s['start_date']}～{s['end_date']}：{error}")
                configs.append(segment_config)
            if problems:
                raise ValueError("以下区间无法运行，请取消勾选后重试：" + "；".join(problems))
            created = now()
            with self._engine.begin() as con:
                con.execute(insert(db.batches).values(
                    id=batch_id, request_key=key, request=request, config=base, discovery_id=discovery_id,
                    selection=plain_json(selection or {}), input_check=plain_json(classification_fingerprint),
                    code_version=code_version(), created_at=created))
                for position, (s, segment_config) in enumerate(zip(request["segments"], configs), 1):
                    con.execute(insert(db.batch_segments).values(
                        batch_id=batch_id, position=position, interval_id=s["interval_id"],
                        start_date=s["start_date"], end_date=s["end_date"]))
                    run_id = uuid.uuid4().hex
                    self._runs.add_queued_run(
                        con, run_id, f"batch:{batch_id}:{position}:1",
                        {"batch_id": batch_id, "position": position, "attempt": 1}, segment_config, None)
                    con.execute(insert(db.batch_attempts).values(
                        batch_id=batch_id, position=position, attempt=1, run_id=run_id, created_at=created))
                    run_ids.append(run_id)

        return submit_once(self._jobs, Job("research_batch", lambda progress: self._run(batch_id, run_ids, progress)),
                           prepare=prepare, find=lambda: find_request(self._engine, db.batches, key, request),
                           new_id=batch_id)

    def retry(self, batch_id: str, position: int, key: str, *,
              precheck: Callable[[], None] | None = None) -> str:
        """A new attempt at one failed segment, with the same configuration.
        It refuses to replay if the segment's data changed since the first
        attempt that got past its input checks; the new run's id."""
        def find() -> str | None:
            with self._engine.connect() as con:
                found = con.execute(select(db.batch_attempts).where(
                    db.batch_attempts.c.request_key == key)).mappings().one_or_none()
            if found and (found["batch_id"], found["position"]) != (batch_id, position):
                raise ValueError(KEY_REUSED)
            return found and found["run_id"]

        if (found := find()) is not None:
            return found
        self._attempts(batch_id, position, failed_only=True)
        run_id = uuid.uuid4().hex
        expected: list[str | None] = []

        def prepare() -> None:
            self._runs.interrupt_unfinished()
            if precheck is not None:
                precheck()
            attempts = self._attempts(batch_id, position, failed_only=True)
            latest = attempts[-1]
            attempt = latest["attempt"] + 1
            # Only a run whose input was accepted stores a fingerprint.
            expected.append(next((a["input_fingerprint"]["sha256"] for a in attempts if a["input_fingerprint"]), None))
            with self._engine.begin() as con:
                self._runs.add_queued_run(
                    con, run_id, f"batch:{batch_id}:{position}:{attempt}",
                    {"batch_id": batch_id, "position": position, "attempt": attempt},
                    latest["config"], latest["run_id"])
                con.execute(insert(db.batch_attempts).values(
                    batch_id=batch_id, position=position, attempt=attempt, run_id=run_id, request_key=key,
                    created_at=now()))

        return submit_once(self._jobs, Job("research_batch", lambda progress: self._run(
            batch_id, [run_id], progress, expect_fingerprint=expected[0])), prepare=prepare, find=find, new_id=run_id)

    def _attempts(self, batch_id: str, position: int, *, failed_only: bool = False) -> list[dict]:
        """The segment's attempts, oldest first, with their runs."""
        a, runs = db.batch_attempts, db.runs
        with self._engine.connect() as con:
            if con.execute(select(db.batches.c.id).where(db.batches.c.id == batch_id)).first() is None:
                raise LookupError("研究批次不存在")
            attempts = [dict(r) for r in con.execute(
                select(a.c.attempt, a.c.run_id, runs.c.status, runs.c.config,
                       runs.c.input_identity.label("input_fingerprint"))
                .join(runs, runs.c.id == a.c.run_id)
                .where(a.c.batch_id == batch_id, a.c.position == position).order_by(a.c.attempt)).mappings()]
        if not attempts:
            raise LookupError(f"该批次没有第 {position} 段")
        if failed_only and attempts[-1]["status"] != FAILED:
            raise ValueError("只有失败的区间可以重试")
        return attempts

    def _run(self, batch_id: str, run_ids: list[str], progress: Progress, *,
             expect_fingerprint: str | None = None) -> JobOutcome:
        """Each run in turn; one segment failing does not stop the others."""
        completed, warnings = 0, []
        for done, run_id in enumerate(run_ids):
            def step(day: dict[str, Any], done: int = done) -> None:
                progress({"batch_id": batch_id, "segments_done": done, "segments_total": len(run_ids), **day})
            try:
                outcome = self._runs.execute(run_id, step, expect_fingerprint=expect_fingerprint)
            except Exception:  # recorded on the run by execute
                continue
            completed += 1
            warnings.extend(outcome.warnings)
        return JobOutcome({"batch_id": batch_id, "completed": completed, "failed": len(run_ids) - completed},
                          sorted(set(warnings)))

    def get(self, batch_id: str) -> dict:
        with self._engine.connect() as con:
            batch = con.execute(select(db.batches).where(db.batches.c.id == batch_id)).mappings().one_or_none()
            if batch is None:
                raise LookupError("研究批次不存在")
            segments = con.execute(select(db.batch_segments).where(db.batch_segments.c.batch_id == batch_id)
                                   .order_by(db.batch_segments.c.position)).mappings().all()
            a, runs = db.batch_attempts, db.runs
            attempts = con.execute(
                select(a.c.position, a.c.attempt, a.c.run_id, a.c.created_at, runs.c.status, runs.c.error,
                       runs.c.retry_of, runs.c.progress, runs.c.result)
                .join(runs, runs.c.id == a.c.run_id).where(a.c.batch_id == batch_id)
                .order_by(a.c.position, a.c.attempt)).mappings().all()
        by_position: dict[int, list] = {}
        for attempt in attempts:
            by_position.setdefault(attempt["position"], []).append(attempt)
        out = []
        for s in segments:
            tries = by_position[s["position"]]
            latest = tries[-1]
            out.append({
                "position": s["position"], "interval_id": s["interval_id"],
                "start_date": s["start_date"], "end_date": s["end_date"],
                "status": latest["status"], "run_id": latest["run_id"], "progress": latest["progress"],
                "error": latest["error"],
                "attempts": [{key: t[key] for key in ("attempt", "run_id", "status", "error", "created_at", "retry_of")}
                             for t in tries],
                "metrics": _metrics(latest["result"]) if latest["status"] == COMPLETED else None,
            })
        return {"id": batch["id"], "created_at": batch["created_at"], "discovery_id": batch["discovery_id"],
                "selection": batch["selection"], "config": batch["config"],
                "classification_fingerprint": batch["input_check"],
                "code_version": batch["code_version"], "status": _status([s["status"] for s in out]),
                "max_batch_runs": MAX_BATCH_RUNS, "segments": out, "distribution": distribution(out)}

    def history(self, page: int = 1, page_size: int = 20) -> dict:
        b = db.batches
        with self._engine.connect() as con:
            total = con.execute(select(func.count()).select_from(b)).scalar_one()
            rows = con.execute(select(b.c.id, b.c.created_at, b.c.discovery_id, b.c.config)
                               .order_by(b.c.created_at.desc(), b.c.id)
                               .offset((page - 1) * page_size).limit(page_size)).mappings().all()
        statuses = self._statuses([r["id"] for r in rows])
        batches = []
        for r in rows:
            found = statuses[r["id"]]
            params = r["config"]["strategy_params"]
            batches.append({
                "id": r["id"], "created_at": r["created_at"], "discovery_id": r["discovery_id"],
                "source_account_id": r["config"]["source_account_id"], "source_name": r["config"]["name"],
                "entry_above": params["entry_above"], "exit_below": params["exit_below"],
                "status": _status(found), "segments": len(found), "completed": found.count(COMPLETED),
                "failed": found.count(FAILED)})
        return {"total": total, "page": page, "page_size": page_size, "batches": batches}

    def for_discovery(self, discovery_id: str) -> list[dict]:
        """The batches run from one discovery, oldest first, with what each selected."""
        b = db.batches
        with self._engine.connect() as con:
            rows = con.execute(select(b.c.id, b.c.created_at, b.c.selection).where(b.c.discovery_id == discovery_id)
                               .order_by(b.c.created_at, b.c.id)).mappings().all()
        statuses = self._statuses([r["id"] for r in rows])
        return [{"id": r["id"], "created_at": r["created_at"], "selection": r["selection"],
                 "status": _status(statuses[r["id"]])} for r in rows]

    def _statuses(self, batch_ids: list[str]) -> dict[str, list[str]]:
        """Each batch's segment statuses (latest attempts), by position."""
        a, runs = db.batch_attempts, db.runs
        with self._engine.connect() as con:
            found = con.execute(select(a.c.batch_id, a.c.position, runs.c.status)
                                .join(runs, runs.c.id == a.c.run_id).where(a.c.batch_id.in_(batch_ids))
                                .order_by(a.c.batch_id, a.c.position, a.c.attempt)).all()
        latest: dict[str, dict[int, str]] = {batch_id: {} for batch_id in batch_ids}
        for batch_id, position, status in found:
            latest[batch_id][position] = status
        return {batch_id: [by[p] for p in sorted(by)] for batch_id, by in latest.items()}


def _status(statuses: list[str]) -> BatchStatus:
    if RUNNING in statuses:
        return RUNNING
    if QUEUED in statuses:
        return QUEUED
    completed = statuses.count(COMPLETED)
    if statuses and completed == len(statuses):
        return COMPLETED
    return PARTIAL if completed else FAILED


def _metrics(result: dict) -> dict:
    return {"sessions": len(result["nav"]), **{key: result[key] for key in (
        "total_return", "topix_return", "excess_return", "max_drawdown", "trades", "fees", "realised_pnl",
        "unrealised_pnl")}, "holdings": len(result["holdings"]), "pending": len(result["pending"])}


def distribution(segments: Sequence[dict]) -> dict:
    """Completed segments side by side, each weighing the same. Independent
    capitals: nothing is chained, compounded or drawn down together."""
    done = [s for s in segments if s["status"] == COMPLETED]
    returns = [s["metrics"]["total_return"] for s in done]
    excess = [s["metrics"]["excess_return"] for s in done]
    n = len(done)

    def ratio(count: int) -> float | None:
        return count / n if n else None

    def worst(field: str) -> dict | None:
        if not done:
            return None
        s = min(done, key=lambda s: s["metrics"][field])
        return {"position": s["position"], "start_date": s["start_date"], "end_date": s["end_date"],
                field: s["metrics"][field]}

    profitable, losing = sum(r > 0 for r in returns), sum(r < 0 for r in returns)
    beat, behind = sum(r > 0 for r in excess), sum(r < 0 for r in excess)
    ranges = sorted([s["start_date"], s["end_date"]] for s in done)
    return {
        "weighting": "equal_per_completed_segment",
        "selected": len(segments), "completed": n,
        "failed": sum(s["status"] == FAILED for s in segments),
        "unfinished": sum(s["status"] in UNFINISHED for s in segments),
        "denominator": n, "returns": returns, "excess_returns": excess,
        "median_return": statistics.median(returns) if n else None,
        "median_excess": statistics.median(excess) if n else None,
        "profitable": profitable, "flat": n - profitable - losing, "losing": losing,
        "profitable_ratio": ratio(profitable),
        "beat_topix": beat, "tied_topix": n - beat - behind, "behind_topix": behind, "beat_ratio": ratio(beat),
        "worst": worst("total_return"), "worst_excess": worst("excess_return"),
        "coverage": {"sessions": sum(s["metrics"]["sessions"] for s in done),
                     "first": ranges[0][0] if ranges else None,
                     "last": max(r[1] for r in ranges) if ranges else None, "ranges": ranges},
    }
