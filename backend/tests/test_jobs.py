"""`Jobs` (spec §8, appendix A.5): one worker thread, one job at a time,
one cross-process lock, and a log of results that survives restarts.

Nothing waits: a job is refused at `submit` while another one — here or in
another process — is running.

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


def one_after_another(jobs: Jobs, *items: Job) -> list[str]:
    ids = []
    for job in items:
        ids.append(jobs.submit(job))
        jobs.wait_until_idle()
    return ids


def test_history_is_newest_first_and_limited(jobs) -> None:
    ids = one_after_another(jobs, *[Job(f"job-{n}", finished()) for n in range(3)])

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


def test_a_failing_job_is_recorded_and_the_next_one_still_runs(jobs) -> None:
    def broken(progress):
        raise RuntimeError("J-Quants 返回 HTTP 403")

    one_after_another(jobs, Job("sync", broken), Job("other", finished()))

    other, failed = jobs.history()
    assert (failed.status, failed.error) == ("failed", "J-Quants 返回 HTTP 403")
    assert other.status == "succeeded"


@pytest.mark.parametrize("second_kind", ["sync", "advance"])
def test_submitting_while_a_job_is_running_is_refused_at_once(jobs, second_kind) -> None:
    """One job at a time, and nothing queues behind it: pressing 立即同步
    twice, or the timer firing during a manual sync, is told so."""
    started, release = threading.Event(), threading.Event()

    def slow(progress):
        started.set()
        release.wait(5)
        return JobOutcome()

    first = jobs.submit(Job("sync", slow))
    assert started.wait(5)

    with pytest.raises(JobsBusy) as refusal:
        jobs.submit(Job(second_kind, finished()))

    release.set()
    jobs.wait_until_idle()
    assert "正在运行" in str(refusal.value)
    assert [result.id for result in jobs.history()] == [first]


def test_submitting_while_another_process_holds_the_lock_is_refused_at_once(jobs, runtime_dir) -> None:
    """The command line's backfill holds the lock for 40 minutes; a sync
    submitted meanwhile is refused, not left waiting behind it."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    other_process = FileLock(runtime_dir / "job.lock")
    other_process.acquire()
    try:
        with pytest.raises(JobsBusy):
            jobs.submit(Job("sync", finished()))
        assert jobs.current() is None
    finally:
        other_process.release()

    jobs.submit(Job("sync", finished()))
    assert jobs.wait_until_idle()
    assert [result.status for result in jobs.history()] == ["succeeded"]


def test_the_lock_is_held_from_submit_until_the_job_ends(jobs, runtime_dir) -> None:
    """Taken at `submit`, not when the worker gets round to the job, so
    the command line cannot slip in between and leave the job waiting."""
    release = threading.Event()
    jobs.submit(Job("sync", lambda progress: release.wait(5) and JobOutcome()))

    with pytest.raises(JobsBusy):
        run_now(Job("sync", finished()), runtime_dir)

    release.set()
    jobs.wait_until_idle()
    assert run_now(Job("sync", finished()), runtime_dir).status == "succeeded"


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
