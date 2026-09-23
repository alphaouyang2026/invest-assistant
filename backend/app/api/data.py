"""`/api/data/*` — the data page."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import DataQuality, DataStatus, JobResultOut, Refusal, SecurityGap, SyncAccepted
from app.jobs import JobsBusy
from app.runtime import sync_job

router = APIRouter(prefix="/api/data", tags=["data"])

RECENT_JOBS = 10


@router.get("/status")
def status(request: Request) -> DataStatus:
    overview = request.app.state.market.overview()
    return DataStatus(
        latest_date=overview.latest_date,
        securities=overview.securities,
        bar_rows=overview.bar_rows,
        recent_jobs=[JobResultOut(**asdict(result)) for result in request.app.state.jobs.history(RECENT_JOBS)],
    )


@router.post("/sync", status_code=202, responses={409: {"model": Refusal, "description": "已有任务正在运行，没有排入"}})
def sync_now(request: Request) -> SyncAccepted:
    try:
        return SyncAccepted(job_id=request.app.state.jobs.submit(sync_job(request.app.state.market)))
    except JobsBusy as busy:
        raise HTTPException(status_code=409, detail=str(busy)) from None


@router.get("/quality")
def quality(request: Request) -> DataQuality:
    report = request.app.state.market.overview().quality
    return DataQuality(
        missing_sessions=report.missing_sessions,
        gaps=[SecurityGap(code=code, missing_sessions=count) for code, count in sorted(report.gaps.items())],
        untradable_rows=report.untradable_rows,
        untradable_on_latest=report.untradable_on_latest,
    )
