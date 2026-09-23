"""Background jobs (spec §8, appendix A.5).

One worker thread takes jobs off one queue, one at a time, because SQLite
has one writer (ADR-0002). Each job first takes `var/job.lock`, which the
command line takes too, so a foreground backfill and the service never
write at once. Every result is appended to `var/jobs.jsonl`; the job in
progress lives only in memory — a restart loses it, and rerunning is the
recovery.

Callers see `submit`, `current` and `history`, plus `run_now` for the
command line.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from filelock import FileLock, Timeout

LOCK_FILE = "job.lock"
LOG_FILE = "jobs.jsonl"

Progress = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class JobOutcome:
    """What a job's function returns: a JSON-able summary and warnings."""

    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Job:
    kind: str  # "sync"; "advance" arrives with ticket 04
    run: Callable[[Progress], JobOutcome]


@dataclass(frozen=True)
class JobStatus:
    id: str
    kind: str
    state: str  # "queued" / "waiting_for_lock" / "running"
    submitted_at: datetime
    started_at: datetime | None
    progress: dict[str, Any] | None


@dataclass(frozen=True)
class JobResult:
    id: str
    kind: str
    status: str  # "succeeded" / "failed"
    started_at: datetime
    finished_at: datetime
    summary: dict[str, Any]
    warnings: list[str]
    error: str | None


class JobsBusy(RuntimeError):
    """Another process holds the job lock."""


def _tokyo_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tokyo"))


@dataclass
class _Entry:
    id: str
    job: Job
    submitted_at: datetime
    state: str = "queued"
    started_at: datetime | None = None
    progress: dict[str, Any] | None = None

    def status(self) -> JobStatus:
        return JobStatus(self.id, self.job.kind, self.state, self.submitted_at, self.started_at, self.progress)


class Jobs:
    def __init__(self, runtime_dir: Path, *, clock: Callable[[], datetime] = _tokyo_now) -> None:
        self._dir = Path(runtime_dir)
        self._clock = clock
        self._changed = threading.Condition()
        self._queue: deque[_Entry] = deque()
        self._active: _Entry | None = None
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._changed:
            self._stopping = True
            self._changed.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def submit(self, job: Job) -> str:
        """Queue `job`; if one of the same kind is already waiting or
        running, that one's id comes back instead."""
        with self._changed:
            for entry in (self._active, *self._queue):
                if entry is not None and entry.job.kind == job.kind:
                    return entry.id
            entry = _Entry(uuid.uuid4().hex[:12], job, self._clock())
            self._queue.append(entry)
            self._changed.notify_all()
            return entry.id

    def current(self) -> JobStatus | None:
        """The job being worked on, else the next one waiting."""
        with self._changed:
            entry = self._active or (self._queue[0] if self._queue else None)
            return None if entry is None else entry.status()

    def history(self, limit: int = 20) -> list[JobResult]:
        """Finished jobs, newest first."""
        return read_history(self._dir, limit)

    def wait_until_idle(self, timeout: float = 10.0) -> bool:
        """True once nothing is queued or running; False if `timeout` ran out."""
        with self._changed:
            return self._changed.wait_for(lambda: self._active is None and not self._queue, timeout)

    def _work(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(self._dir / LOCK_FILE)
        while True:
            with self._changed:
                self._changed.wait_for(lambda: self._stopping or self._queue)
                if self._stopping:
                    return
                entry = self._active = self._queue.popleft()
                entry.state = "waiting_for_lock"

            while not self._stopping:
                try:
                    lock.acquire(timeout=0.2)
                    break
                except Timeout:
                    continue
            else:
                return

            try:
                with self._changed:
                    entry.state, entry.started_at = "running", self._clock()
                _execute(entry.id, entry.job, self._dir, self._clock, entry.started_at, self._set_progress(entry))
            finally:
                lock.release()
                with self._changed:
                    self._active = None
                    self._changed.notify_all()

    def _set_progress(self, entry: _Entry) -> Progress:
        def report(progress: dict[str, Any]) -> None:
            with self._changed:
                entry.progress = dict(progress)
        return report


class DailySync:
    """Queues the sync each session day at 18:00 Tokyo time, and again
    every 30 minutes up to 21:00 while it reports today's data not out.

    `tick()` decides from the clock and the job history alone, so a restart
    in the evening neither skips the day nor syncs it twice. Something has
    to call it periodically: `run_forever` in the service.
    """

    FIRST = time(18, 0)
    LAST = time(21, 0)
    RETRY_AFTER = timedelta(minutes=30)

    def __init__(
        self,
        jobs: Jobs,
        *,
        make_job: Callable[[], Job],
        is_session: Callable[[date], bool],
        clock: Callable[[], datetime] = _tokyo_now,
    ) -> None:
        self._jobs = jobs
        self._make_job = make_job
        self._is_session = is_session
        self._clock = clock

    def tick(self) -> str | None:
        """Submit the sync if it is due; its job id if so."""
        now = self._clock()
        if now.time() < self.FIRST or not self._is_session(now.date()):
            return None
        current = self._jobs.current()
        if current is not None and current.kind == "sync":
            return None
        tonight = [
            result for result in self._jobs.history()
            if result.kind == "sync" and result.started_at.date() == now.date() and result.started_at.time() >= self.FIRST
        ]
        if tonight:
            latest = tonight[0]
            if not latest.summary.get("not_published_yet"):
                return None
            if now.time() > self.LAST or now < latest.finished_at + self.RETRY_AFTER:
                return None
        return self._jobs.submit(self._make_job())

    def run_forever(self, stop: threading.Event, every_seconds: float = 30.0) -> None:
        while not stop.wait(every_seconds):
            try:
                self.tick()
            except Exception:  # a bad tick must not end the timer for good
                structlog.get_logger().exception("daily_sync_tick_failed")


def run_now(job: Job, runtime_dir: Path, *, clock: Callable[[], datetime] = _tokyo_now,
            progress: Progress = lambda _: None) -> JobResult:
    """Run `job` in the calling thread — the command line's way in.

    Refuses rather than waits when the lock is taken: someone at a
    terminal should hear that the service is busy, not stare at nothing.
    """
    runtime_dir = Path(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(runtime_dir / LOCK_FILE)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise JobsBusy("另一个任务正在运行（var/job.lock 已被占用），请稍后再试") from None
    try:
        return _execute(uuid.uuid4().hex[:12], job, runtime_dir, clock, clock(), progress)
    finally:
        lock.release()


def read_history(runtime_dir: Path, limit: int = 20) -> list[JobResult]:
    log = Path(runtime_dir) / LOG_FILE
    if not log.exists():
        return []
    lines = log.read_text(encoding="utf-8").splitlines()
    return [_result_from(json.loads(line)) for line in reversed(lines[-limit:]) if line.strip()]


def _execute(job_id: str, job: Job, runtime_dir: Path, clock: Callable[[], datetime],
             started_at: datetime, progress: Progress) -> JobResult:
    try:
        outcome = job.run(progress)
    except Exception as error:  # a failed job is a result, not a dead worker
        result = JobResult(job_id, job.kind, "failed", started_at, clock(), {}, [], str(error))
    else:
        result = JobResult(job_id, job.kind, "succeeded", started_at, clock(),
                           outcome.summary, outcome.warnings, None)
    with (runtime_dir / LOG_FILE).open("a", encoding="utf-8") as log:
        log.write(json.dumps(_result_to(result), ensure_ascii=False) + "\n")
    return result


def _result_to(result: JobResult) -> dict[str, Any]:
    row = asdict(result)
    row["started_at"] = result.started_at.isoformat()
    row["finished_at"] = result.finished_at.isoformat()
    return row


def _result_from(row: dict[str, Any]) -> JobResult:
    return JobResult(**row | {
        "started_at": datetime.fromisoformat(row["started_at"]),
        "finished_at": datetime.fromisoformat(row["finished_at"]),
    })
