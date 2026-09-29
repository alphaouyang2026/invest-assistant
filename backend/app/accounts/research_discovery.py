"""Interval discovery (04b-B): which ranges of the past matched a TOPIX
regime filter, and batches over the ones the user picks.

A discovery is a job, like any other research job, under the shared writer
lock; reading one never works anything out. It keeps every candidate
interval, numbered 1..N oldest first, and a fingerprint of the TOPIX closes
it read. A batch names intervals by those numbers only — the dates come from
here, never from the client — and is refused when the closes the discovery
read have changed since. Days after the search end are never read, so the
daily sync appending new ones changes nothing.
"""
from __future__ import annotations

import uuid
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import Engine, insert, select, update

from app.accounts import regimes
from app.accounts import research_tables as db
from app.accounts.research import Research
from app.accounts.research_jobs import code_version, find_request, now, plain_json, submit_once
from app.accounts.research_batches import MAX_BATCH_RUNS, ResearchBatches, SegmentSpec, StaleInput
from app.jobs import Job, JobOutcome, Jobs, Progress
from app.market_data import EXEC_CLOSE, MarketData

TOPIX = "TOPIX"


class RegimeDiscoveries:
    def __init__(self, engine: Engine, market: MarketData, jobs: Jobs, batches: ResearchBatches,
                 research: Research) -> None:
        self._engine, self._market, self._jobs = engine, market, jobs
        self._batches, self._research = batches, research

    def definition(self) -> dict:
        """The classification rules, and how far TOPIX goes (for the form's defaults)."""
        first, last = self._topix_span()
        return {**regimes.DEFINITION.as_dict(), "topix_from": first, "topix_through": last}

    def submit(self, request: dict, key: str) -> str:
        """Accept a discovery; the id to poll. Idempotent on `key`."""
        parameters = plain_json({name: request.get(name) for name in ("search_from", "search_to", "trend", "volatility")})
        regimes.RegimeFilter(parameters["trend"], parameters["volatility"])  # names a real trend and level
        discovery_id = uuid.uuid4().hex

        def prepare() -> None:
            # Jobs holds the writer lock: nothing else is running.
            self._research._interrupt_stale()
            self._series(*_range(parameters))
            with self._engine.begin() as con:
                con.execute(insert(db.discoveries).values(
                    id=discovery_id, request_key=key, request=parameters,
                    definition_version=regimes.DEFINITION.version, definition=regimes.DEFINITION.as_dict(),
                    parameters=parameters, status="queued", code_version=code_version(), created_at=now()))

        return submit_once(self._jobs, Job("regime_discovery", lambda progress: self._run(discovery_id, progress)),
                           prepare=prepare, find=lambda: find_request(self._engine, db.discoveries, key, parameters),
                           new_id=discovery_id)

    def _run(self, discovery_id: str, progress: Progress) -> JobOutcome:
        self._set(discovery_id, status="running")
        try:
            parameters = self._row(discovery_id)["parameters"]
            search_from, search_to = _range(parameters)
            sessions, closes = self._series(search_from, search_to)
            found = regimes.discover(sessions, closes, search_from, search_to,
                                     regimes.RegimeFilter(parameters["trend"], parameters["volatility"]))
            fingerprint = regimes.fingerprint(sessions, closes)
            with self._engine.begin() as con:
                if found.intervals:
                    con.execute(insert(db.discovery_intervals), [
                        {"discovery_id": discovery_id, "interval_id": n, "start_date": i.start.isoformat(),
                         "end_date": i.end.isoformat(), "sessions": i.sessions, "data": _interval(i)}
                        for n, i in enumerate(found.intervals, 1)])
                con.execute(update(db.discoveries).where(db.discoveries.c.id == discovery_id).values(
                    status="completed", fingerprint=fingerprint, diagnostics=plain_json(asdict(found.diagnostics)),
                    finished_at=now()))
            progress({"discovery_id": discovery_id, "intervals": len(found.intervals)})
            return JobOutcome({"discovery_id": discovery_id, "intervals": len(found.intervals)})
        except Exception as error:
            self._set(discovery_id, status="failed", error=str(error), finished_at=now())
            raise

    def get(self, discovery_id: str) -> dict:
        row = self._row(discovery_id)
        with self._engine.connect() as con:
            intervals = con.execute(select(db.discovery_intervals)
                                    .where(db.discovery_intervals.c.discovery_id == discovery_id)
                                    .order_by(db.discovery_intervals.c.interval_id)).mappings().all()
        sessions = self._market.calendar().sessions()
        out = []
        for i in intervals:
            # For the page's strategy warm-up hint: open days on record before the start.
            before = bisect_left(sessions, date.fromisoformat(i["start_date"]))
            out.append({**i["data"], "id": i["interval_id"], "start_date": i["start_date"],
                        "end_date": i["end_date"], "sessions": i["sessions"], "sessions_before": before})
        return {**{k: row[k] for k in ("id", "status", "error", "created_at", "finished_at", "definition_version",
                                       "definition", "parameters", "fingerprint", "diagnostics")},
                "intervals": out, "max_batch_runs": MAX_BATCH_RUNS,
                "batches": self._batches.for_discovery(discovery_id)}

    def check(self, discovery_id: str) -> Callable[[], None]:
        """A precheck for a batch, run under the writer lock: the TOPIX closes
        this discovery read must be exactly as they were."""
        row = self._row(discovery_id)

        def precheck() -> None:
            try:
                sessions, closes = self._series(*_range(row["parameters"]))
                now = regimes.fingerprint(sessions, closes)
            except ValueError:
                now = None
            if now is None or now["sha256"] != row["fingerprint"]["sha256"]:
                raise StaleInput("行情自区间发现后已变化，请重新发现后再运行")
        return precheck

    def submit_batch(self, *, discovery_id: str, interval_ids: list[int], source_account_id: int,
                     entry_above: float, exit_below: float, key: str) -> str:
        """Run one configuration over the chosen intervals of a discovery."""
        row = self._row(discovery_id)
        if row["status"] != "completed":
            raise ValueError("区间发现尚未完成，不能运行")
        with self._engine.connect() as con:
            stored = {r["interval_id"]: r for r in con.execute(select(db.discovery_intervals).where(
                db.discovery_intervals.c.discovery_id == discovery_id)).mappings()}
        chosen = sorted(set(interval_ids))
        foreign = [n for n in chosen if n not in stored]
        if foreign:
            raise ValueError("以下区间不属于这次发现：" + "、".join(map(str, foreign)))
        segments = [SegmentSpec(date.fromisoformat(stored[n]["start_date"]),
                                date.fromisoformat(stored[n]["end_date"]), n) for n in chosen]
        return self._batches.submit(
            source_account_id=source_account_id, entry_above=entry_above, exit_below=exit_below,
            segments=segments, key=key, discovery_id=discovery_id,
            selection={"interval_ids": chosen, "candidate_count": len(stored)},
            input_check=row["fingerprint"], precheck=self.check(discovery_id))

    def retry_segment(self, batch_id: str, position: int, key: str) -> str:
        """Retry one failed segment; for a batch from a discovery, only while its TOPIX is unchanged."""
        with self._engine.connect() as con:
            discovery_id = con.execute(select(db.batches.c.discovery_id)
                                       .where(db.batches.c.id == batch_id)).scalar_one_or_none()
        precheck = self.check(discovery_id) if discovery_id else None
        return self._batches.retry(batch_id, position, key, precheck=precheck)

    def _series(self, search_from: date, search_to: date) -> tuple[list[date], dict[date, Decimal | None]]:
        """The open sessions and TOPIX closes a discovery reads: from as far
        back as its first label needs, through `search_to` and never later."""
        if search_from > search_to:
            raise ValueError("搜索起始日不能晚于结束日")
        topix = self._topix()
        if topix.empty:
            raise ValueError("没有 TOPIX 行情，请先同步")
        if search_to > topix.index[-1]:
            raise ValueError(f"搜索结束日超出已有行情（TOPIX 到 {topix.index[-1].isoformat()}）")
        sessions = [d for d in self._market.calendar().sessions() if topix.index[0] <= d <= search_to]
        if not any(d >= search_from for d in sessions):
            raise ValueError("搜索范围内没有开市日")
        sessions = sessions[sessions.index(regimes.lookback_start(sessions, search_from)):]
        closes = {}
        for day in sessions:
            value = topix.get(day)
            closes[day] = None if value is None or pd.isna(value) else value
        return sessions, closes

    def _topix_span(self) -> tuple[date | None, date | None]:
        topix = self._topix()
        return (None, None) if topix.empty else (topix.index[0], topix.index[-1])

    def _topix(self) -> pd.Series:
        """Every stored TOPIX close by date, oldest first (a few thousand rows at most)."""
        frame = self._market.read([TOPIX], date.min, date.max)
        if not frame.dates(TOPIX):
            return pd.Series(dtype=object)
        return frame.wide(EXEC_CLOSE)[TOPIX].sort_index()

    def _row(self, discovery_id: str) -> dict:
        with self._engine.connect() as con:
            row = con.execute(select(db.discoveries)
                              .where(db.discoveries.c.id == discovery_id)).mappings().one_or_none()
        if row is None:
            raise LookupError("区间发现不存在")
        return dict(row)

    def _set(self, discovery_id: str, **values) -> None:
        with self._engine.begin() as con:
            con.execute(update(db.discoveries).where(db.discoveries.c.id == discovery_id).values(**values))


def _range(parameters: dict) -> tuple[date, date]:
    return date.fromisoformat(parameters["search_from"]), date.fromisoformat(parameters["search_to"])


def _interval(interval: regimes.Interval) -> dict:
    """What the list shows beyond the dates: TOPIX at both ends and the RV20 spread, as plain numbers."""
    shown = {key: value for key, value in asdict(interval).items() if key not in ("start", "end", "sessions")}
    shown["topix_start"], shown["topix_end"] = float(interval.topix_start), float(interval.topix_end)
    return shown
