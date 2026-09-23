"""`Jobs` (spec §8, appendix A.5): one worker thread, one queue, one
cross-process lock, and a log of results that survives restarts.

Jobs here are small functions; what a sync job does is the market data
tests' business.
"""

from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from filelock import FileLock

from app.jobs import Job, JobOutcome, Jobs, JobsBusy, run_now

TOKYO = ZoneInfo("Asia/Tokyo")


@pytest.fixture
def runtime_dir(tmp_path):
    return tmp_path / "var"


@pytest.fixture
def jobs(runtime_dir):
    jobs = Jobs(runtime_dir, clock=lambda: datetime(2026, 9, 24, 18, 0, tzinfo=TOKYO))
    jobs.start()
    yield jobs
    jobs.stop()


def finished(summary: dict | None = None, warnings=()):
    return lambda progress: JobOutcome(summary=summary or {}, warnings=list(warnings))


def test_a_submitted_job_runs_and_its_result_is_kept(jobs, runtime_dir) -> None:
    job_id = jobs.submit(Job("sync", finished({"rows_written": 12}, ["2026-09-22 缺日线"])))
    jobs.wait_until_idle()

    [result] = jobs.history()
    assert (result.id, result.kind, result.status) == (job_id, "sync", "succeeded")
    assert result.summary == {"rows_written": 12}
    assert result.warnings == ["2026-09-22 缺日线"]

    reopened = Jobs(runtime_dir)  # after a restart, from var/jobs.jsonl
    assert [r.id for r in reopened.history()] == [job_id]


def test_history_is_newest_first_and_limited(jobs) -> None:
    ids = [jobs.submit(Job(f"job-{n}", finished())) for n in range(3)]
    jobs.wait_until_idle()

    assert [result.id for result in jobs.history(limit=2)] == [ids[2], ids[1]]


def test_the_running_job_and_its_progress_are_visible(jobs) -> None:
    reported, release = threading.Event(), threading.Event()

    def slow(progress):
        progress({"sessions_done": 3, "sessions_total": 10})
        reported.set()
        release.wait(5)
        return JobOutcome()

    job_id = jobs.submit(Job("sync", slow))
    assert reported.wait(5)

    status = jobs.current()
    assert (status.id, status.kind, status.state) == (job_id, "sync", "running")
    assert status.progress == {"sessions_done": 3, "sessions_total": 10}

    release.set()
    jobs.wait_until_idle()
    assert jobs.current() is None


def test_jobs_run_one_at_a_time_in_the_order_submitted(jobs) -> None:
    order, overlap = [], []
    running = threading.Lock()

    def step(name):
        def run(progress):
            if not running.acquire(blocking=False):
                overlap.append(name)
                return JobOutcome()
            order.append(name)
            running.release()
            return JobOutcome()
        return run

    for name in ("a", "b", "c"):
        jobs.submit(Job(name, step(name)))
    jobs.wait_until_idle()

    assert (order, overlap) == (["a", "b", "c"], [])


def test_a_failing_job_is_recorded_and_the_next_one_still_runs(jobs) -> None:
    def broken(progress):
        raise RuntimeError("J-Quants 返回 HTTP 403")

    jobs.submit(Job("sync", broken))
    jobs.submit(Job("other", finished()))
    jobs.wait_until_idle()

    other, failed = jobs.history()
    assert (failed.status, failed.error) == ("failed", "J-Quants 返回 HTTP 403")
    assert other.status == "succeeded"


def test_submitting_a_kind_already_waiting_returns_the_waiting_job(jobs) -> None:
    """Pressing 立即同步 twice, or the 18:00 timer firing during a manual
    sync, should not queue a second sync behind the first."""
    release = threading.Event()
    first = jobs.submit(Job("sync", lambda progress: release.wait(5) and JobOutcome()))

    again = jobs.submit(Job("sync", finished()))

    release.set()
    jobs.wait_until_idle()
    assert again == first
    assert len(jobs.history()) == 1


def test_a_job_waits_while_another_process_holds_the_lock(jobs, runtime_dir) -> None:
    other_process = FileLock(runtime_dir / "job.lock")
    other_process.acquire()
    try:
        jobs.submit(Job("sync", finished()))
        assert jobs.wait_until_idle(timeout=0.5) is False
        assert jobs.current().state == "waiting_for_lock"
    finally:
        other_process.release()

    assert jobs.wait_until_idle()
    assert jobs.history()[0].status == "succeeded"


def test_run_now_refuses_while_the_lock_is_held(runtime_dir) -> None:
    """The command line runs in the foreground and must not queue silently
    behind the service's job."""
    runtime_dir.mkdir(parents=True)
    held = FileLock(runtime_dir / "job.lock")
    held.acquire()
    try:
        with pytest.raises(JobsBusy):
            run_now(Job("sync", finished()), runtime_dir)
    finally:
        held.release()


def test_run_now_runs_in_the_foreground_and_logs_like_the_service(runtime_dir) -> None:
    result = run_now(Job("sync", finished({"rows_written": 5})), runtime_dir)

    assert result.status == "succeeded"
    assert [r.id for r in Jobs(runtime_dir).history()] == [result.id]
