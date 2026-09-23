"""Putting the pieces together, once, for the service and the command line.

Both build `MarketData` and the sync job here, so the job the timer queues,
the one behind 立即同步 and the one `python -m app.cli sync` runs are the
same object built the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from app.config import Settings
from app.db import create_engine_for
from app.jobs import Job, JobOutcome, Progress
from app.market_data import MarketData, SyncProgress
from app.market_data.jquants import HttpJQuantsClient, JQuantsClient


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


def sync_job(market: MarketData) -> Job:
    def run(progress: Progress) -> JobOutcome:
        def forward(step: SyncProgress) -> None:
            progress({
                "sessions_done": step.sessions_done,
                "sessions_total": step.sessions_total,
                "current_session": step.current_session.isoformat(),
            })

        report = market.sync(on_progress=forward)
        return JobOutcome(
            summary={
                "first_session": report.first_session and report.first_session.isoformat(),
                "last_session": report.last_session and report.last_session.isoformat(),
                "rows_written": report.rows_written,
                "not_published_yet": report.not_published_yet,
            },
            warnings=report.warnings,
        )

    return Job("sync", run)
