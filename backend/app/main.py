"""The FastAPI application, with the job thread and the daily sync timer.

Signals arrive in ticket 03, accounts in 04.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI

from app.api import data, jobs as jobs_api
from app.config import Settings
from app.jobs import DailySync, Jobs
from app.log import configure_logging
from app.market_data.jquants import JQuantsClient
from app.runtime import build_market, sync_job


def create_app(
    settings: Settings | None = None,
    *,
    client: JQuantsClient | None = None,
    today: Callable[[], date] | None = None,
) -> FastAPI:
    """`client` and `today` are for tests; the service uses J-Quants and
    the Tokyo clock."""
    configure_logging()
    settings = settings or Settings()
    market = build_market(settings, client=client, today=today)
    jobs = Jobs(settings.runtime_dir)
    timer = DailySync(
        jobs,
        make_job=lambda: sync_job(market),
        is_session=lambda day: market.calendar().is_session(day),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        jobs.start()
        ticking = threading.Thread(target=timer.run_forever, args=(stop,), name="daily-sync", daemon=True)
        ticking.start()
        try:
            yield
        finally:
            stop.set()
            jobs.stop()

    app = FastAPI(title="invest-assistant", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.market = market
    app.state.jobs = jobs
    app.include_router(data.router)
    app.include_router(jobs_api.router)
    return app


app = create_app()
