"""Response shapes. These are what the OpenAPI document — and so the
generated frontend client — says the API returns."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class JobResultOut(BaseModel):
    id: str
    kind: str
    status: str  # "succeeded" / "failed"
    started_at: datetime
    finished_at: datetime
    summary: dict[str, Any]
    warnings: list[str]
    error: str | None


class JobStatusOut(BaseModel):
    id: str
    kind: str
    state: str  # "queued" / "waiting_for_lock" / "running"
    submitted_at: datetime
    started_at: datetime | None
    progress: dict[str, Any] | None


class DataStatus(BaseModel):
    latest_date: date | None
    securities: int
    bar_rows: int
    recent_jobs: list[JobResultOut]


class SyncAccepted(BaseModel):
    job_id: str


class SecurityGap(BaseModel):
    code: str
    missing_sessions: int


class DataQuality(BaseModel):
    missing_sessions: list[date]
    gaps: list[SecurityGap]
    untradable_rows: int
    untradable_on_latest: int
