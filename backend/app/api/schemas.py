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


class AccountIn(BaseModel):
    """A new account (spec §3.5); anything left out takes its default."""

    name: str
    strategy: str
    start_date: date
    strategy_params: dict[str, Any] = {}
    initial_cash: float = 10_000_000
    max_positions: int = 10
    max_weight: float = 0.10
    cash_floor: float = 0.05
    commission_rate: float = 0.0
    commission_min: float = 0.0
    slippage: float = 0.001


class AccountCreated(BaseModel):
    id: int
    advance_job_id: str | None  # None when another job was running; the next sync advances it
    advance_refused: str | None


class AccountSummaryOut(BaseModel):
    id: int
    name: str
    strategy: str
    start_date: date
    advanced_through: date | None
    status: str  # "active" / "stopped"
    total_return: float | None
    max_drawdown: float | None


class FiguresOut(BaseModel):
    """Spec §7.4. Dividends and tax are not included."""

    total_return: float
    annualised_return: float | None
    max_drawdown: float
    sharpe: float | None
    win_rate: float | None
    average_holding_sessions: float | None
    annual_turnover: float | None
    excess_annualised_return: float | None  # over TOPIX


class HoldingOut(BaseModel):
    code: str
    quantity: int
    opened_on: date
    cost: float
    close: float
    value: float


class OrderOut(BaseModel):
    """An order or an account event (spec §3.6)."""

    id: int | None
    kind: str  # buy / sell / split_adjustment / delisting_settlement
    code: str
    signal_date: date
    execution_date: date
    planned_quantity: int
    priority: float | None
    reason: dict[str, Any]
    status: str  # pending / filled / expired / skipped
    outcome_reason: str | None
    filled_quantity: int
    fill_price: float | None
    fees: float
    cash_delta: float


class AccountDetailOut(BaseModel):
    id: int
    name: str
    strategy: str
    strategy_params: dict[str, Any]
    rules: dict[str, float]
    costs: dict[str, float]
    start_date: date
    advanced_through: date | None
    status: str
    backtest_data_mark: dict[str, Any] | None
    figures: FiguresOut | None
    holdings: list[HoldingOut]
    pending: list[OrderOut]  # for the next open


class NavPointOut(BaseModel):
    date: date
    nav: float
    nav_curve: float    # 1 on the first session
    topix_curve: float  # 1 on the first session
    drawdown: float     # below the highest NAV so far, 0 or more


class StrategyOut(BaseModel):
    name: str
    defaults: dict[str, Any]
