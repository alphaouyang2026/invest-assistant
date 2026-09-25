"""Putting the pieces together, once, for the service and the command line.

Both build `MarketData`, `Accounts` and the jobs here, so the job the timer
queues, the one behind 立即同步 and the one `python -m app.cli sync` runs
are the same object built the same way — and likewise for advancing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from app.accounts import Accounts
from app.config import Settings
from app.db import create_engine_for
from app.jobs import Job, JobOutcome, Progress
from app.market_data import MarketData, SyncProgress
from app.market_data.jquants import HttpJQuantsClient, JQuantsClient
from app.strategies import Strategy, build_strategy


class _KeyOnDemandClient:
    """The HTTP adapter, built the first time something is fetched.

    The service must start without `JQUANTS_API_KEY` (ticket 01); only a
    sync needs it, and that is where its absence should be reported.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: HttpJQuantsClient | None = None

    def __getattr__(self, name: str) -> Any:
        if self._client is None:
            self._client = HttpJQuantsClient(self._settings.require_jquants_api_key())
        return getattr(self._client, name)


def build_market(
    settings: Settings,
    *,
    client: JQuantsClient | None = None,
    today: Callable[[], date] | None = None,
) -> MarketData:
    extras = {} if today is None else {"today": today}
    return MarketData(create_engine_for(settings), client or _KeyOnDemandClient(settings), **extras)


def build_accounts(
    settings: Settings,
    market: MarketData,
    *,
    strategies: Callable[[str, Mapping[str, Any]], Strategy] | None = None,
) -> Accounts:
    """`strategies` is for tests; the service builds the real ones."""
    return Accounts(create_engine_for(settings), market, build_strategy=strategies or build_strategy)


def advance_job(accounts: Accounts, account_id: int | None = None) -> Job:
    """One account, or every active one (spec §8)."""
    def run(progress: Progress) -> JobOutcome:
        advanced, warnings = _advance(accounts, account_id, progress)
        return JobOutcome(summary={"accounts_advanced": len(advanced), "accounts": advanced}, warnings=warnings)

    return Job("advance", run)


def _advance(accounts: Accounts, account_id: int | None, progress: Progress) -> tuple[list[dict], list[str]]:
    if account_id is not None:
        targets = [(account_id, str(account_id))]
    else:
        targets = [(summary.id, summary.name) for summary in accounts.list(active_only=True)]
    advanced, warnings = [], []
    for done, (target, name) in enumerate(targets):
        progress({"account": name, "accounts_done": done, "accounts_total": len(targets)})
        report = accounts.advance(target)
        advanced.append({"id": target, "name": name, "sessions": len(report.sessions),
                         "through": report.sessions[-1].isoformat() if report.sessions else None})
        warnings += [f"{name}：{warning}" for warning in report.warnings]
    return advanced, warnings


def sync_job(market: MarketData, accounts: Accounts | None = None) -> Job:
    """The sync, then — when it succeeds — every active account advanced to
    the sessions it brought in, in the same job: one writer at a time."""
    def run(progress: Progress) -> JobOutcome:
        def forward(step: SyncProgress) -> None:
            progress({
                "sessions_done": step.sessions_done,
                "sessions_total": step.sessions_total,
                "current_session": step.current_session.isoformat(),
            })

        report = market.sync(on_progress=forward)
        advanced, account_warnings = _advance(accounts, None, progress) if accounts is not None else ([], [])
        return JobOutcome(
            summary={
                "first_session": report.first_session and report.first_session.isoformat(),
                "last_session": report.last_session and report.last_session.isoformat(),
                "rows_written": report.rows_written,
                "not_published_yet": report.not_published_yet,
                "accounts_advanced": len(advanced),
            },
            warnings=report.warnings + account_warnings,
        )

    return Job("sync", run)
