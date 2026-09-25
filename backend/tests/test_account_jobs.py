"""Advancing accounts as a job (spec §8): after every successful sync, all
active accounts; on the command line, one account or all of them — under
the same `var/job.lock` as the service."""

from __future__ import annotations

from app.accounts import Accounts, AccountSpec
from app.cli import main
from app.config import Settings
from app.jobs import read_history
from app.runtime import sync_job
from app.strategies import Disposition
from tests.account_market import SESSIONS, Script, synced

PLAN = {SESSIONS[1]: {"13010": Disposition.HOLD}}


def test_a_sync_goes_on_to_advance_every_active_account(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10})
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(PLAN))
    active = accounts.create(AccountSpec(name="动", strategy="script", start_date=SESSIONS[1]))
    stopped = accounts.create(AccountSpec(name="停", strategy="script", start_date=SESSIONS[1]))
    accounts.stop(stopped)

    outcome = sync_job(market, accounts).run(lambda progress: None)

    assert outcome.summary["accounts_advanced"] == 1
    assert accounts.report(active).account["advanced_through"] == SESSIONS[-1]
    assert accounts.report(stopped).account["advanced_through"] is None


def test_advance_on_the_command_line_moves_one_account_or_all_active_ones(migrated_database, capsys) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10})
    scripted = {"build_strategy": lambda name, params: Script(PLAN)}
    accounts = Accounts(migrated_database, market, **scripted)
    first = accounts.create(AccountSpec(name="一", strategy="script", start_date=SESSIONS[1]))
    second = accounts.create(AccountSpec(name="二", strategy="script", start_date=SESSIONS[1]))

    assert main(["advance", "--account", str(first)], today=lambda: SESSIONS[-1], **scripted) == 0
    assert accounts.report(first).account["advanced_through"] == SESSIONS[-1]
    assert "完成：一" in capsys.readouterr().out  # its name, not its id
    assert accounts.report(second).account["advanced_through"] is None

    assert main(["advance"], today=lambda: SESSIONS[-1], **scripted) == 0
    assert accounts.report(second).account["advanced_through"] == SESSIONS[-1]
    assert "二" in capsys.readouterr().out
    assert [r.kind for r in read_history(Settings(_env_file=None).runtime_dir)] == ["advance", "advance"]
