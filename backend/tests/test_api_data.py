"""The data page's API: `/api/data/*` and `/api/jobs/current`.

Handlers only translate (spec A.6), so these check the shapes and the
wiring — that 立即同步 really queues the sync and the page can watch it —
not the rules behind them.
"""

from __future__ import annotations

import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

from app.config import Settings
from app.main import create_app
from tests.fakes import FakeJQuants, bar, listed

D1, D2, D3 = date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 24)


@pytest.fixture
def fake():
    bars = {D1: [bar("13010", D1), bar("13020", D1)], D3: [bar("13010", D3, close=None), bar("13020", D3)]}
    return FakeJQuants([D1, D2, D3], bars=bars, roster=[listed("13010"), listed("13020")])


@pytest.fixture
def api(migrated_database, fake):
    app = create_app(Settings(_env_file=None), client=fake, today=lambda: D3)
    with TestClient(app) as client:
        yield client


def wait_for_idle(api: TestClient) -> None:
    deadline = time.monotonic() + 10
    while api.get("/api/jobs/current").json() is not None:
        assert time.monotonic() < deadline, "the job never finished"
        time.sleep(0.02)


def test_status_of_an_empty_database(api) -> None:
    assert api.get("/api/data/status").json() == {
        "latest_date": None, "securities": 0, "bar_rows": 0, "recent_jobs": [],
    }
    assert api.get("/api/jobs/current").json() is None


def test_sync_now_queues_the_sync_and_the_status_shows_its_result(api) -> None:
    response = api.post("/api/data/sync")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    wait_for_idle(api)

    status = api.get("/api/data/status").json()
    assert (status["latest_date"], status["securities"], status["bar_rows"]) == ("2026-09-24", 2, 4)
    [job] = status["recent_jobs"]
    assert (job["id"], job["kind"], job["status"]) == (job_id, "sync", "succeeded")
    assert job["summary"]["rows_written"] == 4
    assert any("2026-09-22" in warning for warning in job["warnings"])


def test_quality_is_worked_out_on_request(api) -> None:
    api.post("/api/data/sync")
    wait_for_idle(api)

    assert api.get("/api/data/quality").json() == {
        "missing_sessions": ["2026-09-22"],
        "gaps": [],
        "untradable_rows": 1,
        "untradable_on_latest": 1,
    }


def test_sync_now_is_refused_with_the_reason_while_another_job_holds_the_lock(api) -> None:
    held = FileLock(Settings(_env_file=None).runtime_dir / "job.lock")
    held.acquire()
    try:
        response = api.post("/api/data/sync")
    finally:
        held.release()

    assert response.status_code == 409
    assert "另一个任务正在运行" in response.json()["detail"]
    assert api.get("/api/jobs/current").json() is None
