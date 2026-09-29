"""Interval discovery and research batch HTTP translation (04b-B); GET
handlers only read, discovery and every batch run are jobs."""
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.accounts.research_batches import StaleInput
from app.api.research import ResearchAccepted
from app.api.schemas import Refusal
from app.jobs import JobsBusy

router = APIRouter(prefix="/api/research", tags=["research"])

Status = Literal["queued", "running", "completed", "failed"]
BatchStatus = Literal["queued", "running", "completed", "partial", "failed"]
Span = tuple[date, date]


class RegimeFormulas(BaseModel):
    ma200: str
    gap: str
    slope20: str
    trend: str
    rv20: str
    rv_threshold: str
    vol: str
    unknown: str


class RegimeRules(BaseModel):
    """The fixed classification definition; a change to it is a new version."""
    version: str
    index: str
    field: str
    ma_sessions: int
    slope_sessions: int
    gap_threshold: str
    rv_sessions: int
    annualisation: int
    rv_history: int
    short_sessions: int
    trend_min_closes: int
    full_min_closes: int
    formulas: RegimeFormulas


class RegimeDefinition(RegimeRules):
    topix_from: date | None
    topix_through: date | None


class DiscoveryIn(BaseModel):
    request_key: UUID
    search_from: date
    search_to: date
    trend: Literal["up", "down", "neutral"]
    volatility: Literal["high", "low"] | None = None


class DiscoveryParameters(BaseModel):
    search_from: date
    search_to: date
    trend: Literal["up", "down", "neutral"]
    volatility: Literal["high", "low"] | None


class ClassificationFingerprint(BaseModel):
    """The TOPIX closes a discovery read (from its look-back start through the search end)."""
    model_config = ConfigDict(populate_by_name=True)
    sha256: str
    definition_version: str
    from_: date = Field(alias="from")
    through: date
    sessions: int


class DiscoveryDiagnostics(BaseModel):
    search_sessions: int
    matched_sessions: int
    warmup_unknown: list[Span]
    gap_unknown: list[Span]
    gaps: list[date]
    trend_counts: dict[str, int]
    vol_counts: dict[str, int]


class IntervalOut(BaseModel):
    id: int
    start_date: date
    end_date: date
    sessions: int
    topix_start: float
    topix_end: float
    topix_return: float
    rv20_min: float | None
    rv20_max: float | None
    single_day: bool
    short: bool
    truncated_start: bool
    at_search_end: bool
    sessions_before: int


class BatchSelection(BaseModel):
    interval_ids: list[int] = []
    candidate_count: int | None = None


class BatchRef(BaseModel):
    id: str
    created_at: str
    selection: BatchSelection
    status: BatchStatus


class DiscoveryDetail(BaseModel):
    id: str
    status: Status
    error: str | None
    created_at: str
    finished_at: str | None
    definition_version: str
    definition: RegimeRules
    parameters: DiscoveryParameters
    fingerprint: ClassificationFingerprint | None
    diagnostics: DiscoveryDiagnostics | None
    intervals: list[IntervalOut]
    max_batch_runs: int
    batches: list[BatchRef]


class BatchIn(BaseModel):
    request_key: UUID
    discovery_id: str
    interval_ids: list[int] = Field(min_length=1)
    source_account_id: int = Field(gt=0)
    entry_above: float = Field(default=0.5, ge=-1, le=1, allow_inf_nan=False)
    exit_below: float = Field(default=-0.1, ge=-1, le=1, allow_inf_nan=False)


class BatchRetryIn(BaseModel):
    request_key: UUID


class BatchRetryAccepted(BaseModel):
    id: str
    run_id: str


class BatchConfig(BaseModel):
    """The source's configuration frozen for every segment; each run adds its own range."""
    name: str
    strategy: str
    strategy_params: dict[str, Any]
    portfolio_rules: dict[str, Any]
    costs: dict[str, str]
    source_account_id: int


class SegmentMetrics(BaseModel):
    sessions: int
    total_return: float
    topix_return: float
    excess_return: float
    max_drawdown: float
    trades: int
    fees: float
    realised_pnl: float
    unrealised_pnl: float
    holdings: int
    pending: int


class SegmentAttempt(BaseModel):
    attempt: int
    run_id: str
    status: Status
    error: str | None
    created_at: str
    retry_of: str | None


class BatchSegment(BaseModel):
    position: int
    interval_id: int | None
    start_date: date
    end_date: date
    status: Status
    run_id: str
    progress: dict[str, Any]
    error: str | None
    attempts: list[SegmentAttempt]
    metrics: SegmentMetrics | None


class WorstSegment(BaseModel):
    position: int
    start_date: date
    end_date: date
    total_return: float


class WorstExcessSegment(BaseModel):
    position: int
    start_date: date
    end_date: date
    excess_return: float


class Coverage(BaseModel):
    sessions: int
    first: date | None
    last: date | None
    ranges: list[Span]


class Distribution(BaseModel):
    """Completed segments side by side, each weighing the same; nothing chained."""
    weighting: Literal["equal_per_completed_segment"]
    selected: int
    completed: int
    failed: int
    unfinished: int
    denominator: int
    returns: list[float]
    excess_returns: list[float]
    median_return: float | None
    median_excess: float | None
    profitable: int
    flat: int
    losing: int
    profitable_ratio: float | None
    beat_topix: int
    tied_topix: int
    behind_topix: int
    beat_ratio: float | None
    worst: WorstSegment | None
    worst_excess: WorstExcessSegment | None
    coverage: Coverage


class BatchDetail(BaseModel):
    id: str
    created_at: str
    discovery_id: str | None
    selection: BatchSelection
    config: BatchConfig
    input_check: dict[str, Any] | None
    code_version: str
    status: BatchStatus
    max_batch_runs: int
    segments: list[BatchSegment]
    distribution: Distribution


class BatchSummary(BaseModel):
    id: str
    created_at: str
    discovery_id: str | None
    source_account_id: int
    source_name: str
    entry_above: float
    exit_below: float
    status: BatchStatus
    segments: int
    completed: int
    failed: int


class BatchHistory(BaseModel):
    total: int
    page: int
    page_size: int
    batches: list[BatchSummary]


def _call(call):
    try:
        return call()
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except StaleInput as error:
        raise HTTPException(412, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except JobsBusy as error:
        raise HTTPException(409, str(error)) from None


ERRORS = {code: {"model": Refusal} for code in (404, 409, 422)}
STALE = {**ERRORS, 412: {"model": Refusal}}


@router.get("/regimes/definition")
def definition(request: Request) -> RegimeDefinition:
    return request.app.state.regime_discoveries.definition()


@router.post("/discoveries", status_code=202, responses=ERRORS)
def discover(request: Request, body: DiscoveryIn) -> ResearchAccepted:
    discovery_id = _call(lambda: request.app.state.regime_discoveries.submit(
        body.model_dump(mode="json", exclude={"request_key"}), str(body.request_key)))
    return ResearchAccepted(id=discovery_id)


@router.get("/discoveries/{discovery_id}", responses=ERRORS)
def discovery(request: Request, discovery_id: str) -> DiscoveryDetail:
    return _call(lambda: request.app.state.regime_discoveries.get(discovery_id))


@router.post("/batches", status_code=202, responses=STALE)
def submit_batch(request: Request, body: BatchIn) -> ResearchAccepted:
    batch_id = _call(lambda: request.app.state.regime_discoveries.submit_batch(
        discovery_id=body.discovery_id, interval_ids=body.interval_ids,
        source_account_id=body.source_account_id, entry_above=body.entry_above, exit_below=body.exit_below,
        key=str(body.request_key)))
    return ResearchAccepted(id=batch_id)


@router.get("/batches")
def batches(request: Request, page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100)) -> BatchHistory:
    return request.app.state.research_batches.history(page, page_size)


@router.get("/batches/{batch_id}", responses=ERRORS)
def batch(request: Request, batch_id: str) -> BatchDetail:
    return _call(lambda: request.app.state.research_batches.get(batch_id))


@router.post("/batches/{batch_id}/segments/{position}/retry", status_code=202, responses=STALE)
def retry_segment(request: Request, batch_id: str, position: int, body: BatchRetryIn) -> BatchRetryAccepted:
    run_id = _call(lambda: request.app.state.regime_discoveries.retry_segment(
        batch_id, position, str(body.request_key)))
    return BatchRetryAccepted(id=batch_id, run_id=run_id)
