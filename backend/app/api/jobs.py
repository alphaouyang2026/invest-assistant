"""`/api/jobs/*`."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from app.api.schemas import JobStatusOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/current")
def current(request: Request) -> JobStatusOut | None:
    status = request.app.state.jobs.current()
    return None if status is None else JobStatusOut(**asdict(status))
