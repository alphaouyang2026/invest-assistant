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
    state: str  # "queued" / "running"
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


class Refusal(BaseModel):
    """Why a request was turned away (FastAPI's `HTTPException` shape)."""

    detail: str


class SecurityGap(BaseModel):
    code: str
    missing_sessions: int


class DataQuality(BaseModel):
    missing_sessions: list[date]
    gaps: list[SecurityGap]
    untradable_rows: int
    untradable_on_latest: int


class CandidateOut(BaseModel):
    code: str
    name: str
    market: str | None
    priority: float | None
    reason_codes: list[str]


class SignalsOut(BaseModel):
    strategy: str
    date: date
    candidates: list[CandidateOut]  # best first


class InstrumentOut(BaseModel):
    code: str
    name: str
    name_en: str
    market: str | None  # its market now; None once it has left the roster


class BarOut(BaseModel):
    """Research prices: comparable across splits. None on a halted day."""

    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class PlotOut(BaseModel):
    indicator: str
    pane: str  # "price": over the candles; "separate": its own pane


class LinePoint(BaseModel):
    date: date
    value: float | None  # None before the line has a value


class SecurityBarsOut(BaseModel):
    code: str
    bars: list[BarOut]
    plots: list[PlotOut]
    lines: dict[str, list[LinePoint]]  # one per plot
    entries: list[date]                # sessions it could have been bought from, holding nothing
