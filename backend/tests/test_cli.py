"""`python -m app.cli sync`: the same sync, in the foreground, and never
at the same time as the service's job."""

from __future__ import annotations

from datetime import date

from filelock import FileLock

from app.cli import main
from app.config import Settings
from app.jobs import read_history
from tests.fakes import FakeJQuants, bar, listed

DAY = date(2026, 9, 24)


def test_sync_runs_in_the_foreground_and_is_logged_like_a_service_job(migrated_database, capsys) -> None:
    client = FakeJQuants([DAY], bars={DAY: [bar("13010", DAY)]}, roster=[listed("13010")])

    code = main(["sync"], client=client, today=lambda: DAY)

    assert code == 0
    assert "2026-09-24" in capsys.readouterr().out
    [result] = read_history(Settings(_env_file=None).runtime_dir)
    assert (result.kind, result.status, result.summary["rows_written"]) == ("sync", "succeeded", 1)


def test_sync_refuses_while_the_service_holds_the_job_lock(migrated_database, capsys) -> None:
    runtime_dir = Settings(_env_file=None).runtime_dir
    client = FakeJQuants([DAY], bars={DAY: [bar("13010", DAY)]}, roster=[listed("13010")])
    held = FileLock(runtime_dir / "job.lock")
    held.acquire()
    try:
        code = main(["sync"], client=client, today=lambda: DAY)
    finally:
        held.release()

    assert code == 1
    assert "另一个任务正在运行" in capsys.readouterr().err
    assert client.bar_requests == []
