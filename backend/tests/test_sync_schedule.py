"""The daily sync timer (spec §8), driven by a clock the test turns.

Each session day at 18:00 Tokyo time a sync is queued; while the sync says
today's data is not out yet, it is queued again 30 minutes after the last
attempt finished, up to 21:00.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from filelock import FileLock

from app.jobs import DailySync, Job, JobOutcome, Jobs

TOKYO = ZoneInfo("Asia/Tokyo")
SESSION, HOLIDAY = date(2026, 9, 24), date(2026, 9, 23)


class Clock:
    def __init__(self, day: date = SESSION) -> None:
        self.day, self.at = day, time(17, 0)

    def __call__(self) -> datetime:
        return datetime.combine(self.day, self.at, TOKYO)


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    jobs = Jobs(tmp_path / "var", clock=clock)
    jobs.start()
    published = {"yet": False}

    def sync_job() -> Job:
        return Job("sync", lambda progress: JobOutcome(summary={"not_published_yet": not published["yet"]}))

    timer = DailySync(jobs, make_job=sync_job, is_session=lambda day: day != HOLIDAY, clock=clock)

    def tick_at(hour: int, minute: int = 0) -> bool:
        """Move the clock, tick, let any queued sync finish; did one run?"""
        clock.at = time(hour, minute)
        submitted = timer.tick()
        jobs.wait_until_idle()
        return submitted is not None

    yield clock, published, tick_at
    jobs.stop()


@pytest.fixture
def lock_file(tmp_path):
    return tmp_path / "var" / "job.lock"


def test_nothing_before_six_in_the_evening_then_a_sync_at_six(world) -> None:
    _, published, tick_at = world
    published["yet"] = True

    assert tick_at(17, 59) is False
    assert tick_at(18, 0) is True
    assert tick_at(18, 1) is False  # done for the day
    assert tick_at(20, 0) is False


def test_no_sync_on_a_day_the_market_is_closed(world) -> None:
    clock, published, tick_at = world
    clock.day = HOLIDAY
    published["yet"] = True

    assert tick_at(18, 0) is False


def test_data_not_out_is_retried_every_30_minutes_until_nine(world) -> None:
    _, _, tick_at = world

    ran = {f"{h}:{m:02d}": tick_at(h, m) for h, m in [
        (18, 0), (18, 15), (18, 30), (18, 45), (19, 0), (20, 30), (21, 0), (21, 30),
    ]}

    assert ran == {
        "18:00": True, "18:15": False, "18:30": True, "18:45": False,
        "19:00": True, "20:30": True, "21:00": True, "21:30": False,
    }


def test_retries_stop_once_the_data_is_out(world) -> None:
    _, published, tick_at = world
    assert tick_at(18, 0) is True

    published["yet"] = True
    assert tick_at(18, 30) is True
    assert tick_at(19, 0) is False


def test_a_sync_refused_because_the_lock_is_held_is_tried_again_on_the_next_tick(world, lock_file) -> None:
    """The command line is backfilling at 18:00: the timer is refused,
    shrugs, and gets in once the backfill lets go."""
    _, published, tick_at = world
    published["yet"] = True
    backfill = FileLock(lock_file)
    backfill.acquire()
    try:
        assert tick_at(18, 0) is False
    finally:
        backfill.release()

    assert tick_at(18, 1) is True
