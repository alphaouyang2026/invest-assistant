"""Model experiment HTTP translation (ticket 06a). Registering and retrying
are jobs; GET handlers only read what a finished experiment stored."""
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.research_jobs import RunStatus
from app.api.research import ERRORS, call_service
from app.api.schemas import NavPointOut, OrderOut, ResearchHolding
from app.experiments.contract import DEFAULTS, SUPPORTED_ACTIONS, TASK, UNSUPPORTED_ACTIONS, ModelRole, Scenario
from app.experiments.features import FEATURE_NAMES, FEATURES_V1
from app.experiments.service import FailureKind
from app.experiments.trainers import TRAINER_DEFAULTS
from app.market_data import UniverseRule

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

EvidenceStatus = Literal["exploratory", "insufficient_evidence"]


# --- registering ---------------------------------------------------------------

class ExperimentRequest(BaseModel):
    """What a new experiment's contract is frozen from. The initial capital,
    portfolio rules and costs left out (null) take the source account's when
    one is named — then they must be left out — or else the defaults."""
    name: str = Field(default=DEFAULTS["name"], max_length=100)
    test_from: date
    test_to: date
    train_sessions: int = DEFAULTS["train_sessions"]
    test_sessions: int = DEFAULTS["test_sessions"]
    expanding: bool = DEFAULTS["expanding"]
    rebalance_sessions: int = DEFAULTS["rebalance_sessions"]
    max_holding_sessions: int = DEFAULTS["max_holding_sessions"]
    trainer: str = DEFAULTS["trainer"]
    trainer_params: dict[str, Any] = DEFAULTS["trainer_params"]
    baselines: list[str] = DEFAULTS["baselines"]
    source_account_id: int | None = Field(default=None, gt=0)
    initial_cash: float | None = Field(default=None, allow_inf_nan=False)
    max_positions: int | None = None
    max_weight: float | None = Field(default=None, allow_inf_nan=False)
    cash_floor: float | None = Field(default=None, allow_inf_nan=False)
    max_adv20_fraction: float | None = Field(default=DEFAULTS["max_adv20_fraction"], allow_inf_nan=False)  # null: no cap
    commission_rate: float | None = Field(default=None, allow_inf_nan=False)
    commission_min: float | None = Field(default=None, allow_inf_nan=False)
    slippage: float | None = Field(default=None, allow_inf_nan=False)
    stress_bps: list[float] = DEFAULTS["stress_bps"]  # each a stress scenario's addition to the base slippage
    min_coverage: float = Field(default=DEFAULTS["min_coverage"], allow_inf_nan=False)
    min_training_samples: int = DEFAULTS["min_training_samples"]
    min_labelled_days: int = DEFAULTS["min_labelled_days"]
    min_trades: int = DEFAULTS["min_trades"]
    actions: list[str] = DEFAULTS["actions"]


class ExperimentIn(ExperimentRequest):
    request_key: UUID


class ExperimentRetryIn(BaseModel):
    request_key: UUID


class ExperimentAccepted(BaseModel):
    id: str


class TaskOut(BaseModel):
    name: str
    decision: str
    label: str
    horizon: int
    label_sessions: int


class FeaturesOut(BaseModel):
    version: str
    names: list[str]


class ExperimentDefaults(BaseModel):
    """For the registration form: every default, the trainers and their
    parameters, the actions a contract may declare, and how far history
    has been seen — what a contract registered now would freeze."""
    defaults: dict[str, Any]
    trainers: dict[str, dict[str, Any]]
    supported_actions: list[str]
    unsupported_actions: list[str]
    task: TaskOut
    features: FeaturesOut
    viewed_through: date | None


# --- the frozen contract ----------------------------------------------------------

class FoldTerms(BaseModel):
    train_sessions: int
    test_sessions: int
    expanding: bool


class PolicyTerms(BaseModel):
    strategy: str
    anchor: date
    rebalance_sessions: int
    max_holding_sessions: int  # 0: no limit
    warmup_sessions: int
    missing_scores: str
    score_missing: str


class ExperimentRules(BaseModel):
    initial_cash: str
    max_positions: int
    max_weight: str
    cash_floor: str
    max_adv20_fraction: str | None = None  # absent: no cap


class ExperimentCosts(BaseModel):
    commission_rate: str
    commission_min: str
    slippage: str


class BaselineTerms(BaseModel):
    trainer: str
    params: dict[str, Any]


class ModelTerms(BaselineTerms):
    search_budget: int


class StressScenario(BaseModel):
    extra_bps: str  # added to the base slippage, each side
    slippage: str   # what that makes, each side


class StressTerms(BaseModel):
    basis: str      # how a stress scenario is worked out: fees as at the base costs
    scenarios: list[StressScenario]


class Minimums(BaseModel):
    coverage: float
    training_samples: int  # in each of the model's folds
    labelled_days: int     # decision days with a rank IC
    trades: int


class ExperimentContract(BaseModel):
    version: str
    name: str
    task: TaskOut
    data: dict[str, str]
    features: FeaturesOut
    universe_rule: UniverseRule
    test_from: date
    test_to: date
    folds: FoldTerms
    policy: PolicyTerms
    portfolio_rules: ExperimentRules
    costs: ExperimentCosts
    stress: StressTerms
    model: ModelTerms
    baselines: list[BaselineTerms]
    benchmarks: list[str]
    minimums: Minimums
    viewed_through: date | None
    actions: list[str]
    source_account_id: int | None


# --- the report -------------------------------------------------------------------

class FoldOut(BaseModel):
    number: int
    train_from: date
    train_to: date
    test_from: date
    test_to: date
    viewed: bool  # its test segment had been seen before registration: exploratory


class DiagnosticSummary(BaseModel):
    decision_days: int
    unavailable_days: int  # decision days the model had no scores (its fold failed)
    ic_days: int
    ic_mean: float | None
    ic_std: float | None
    coverage_mean: float | None
    coverage_min: float | None


class FoldDiagnostics(DiagnosticSummary):
    fold: int


class DiagnosticDay(BaseModel):
    date: date
    fold: int | None
    available: bool
    universe: int
    scored: int
    coverage: float | None
    labelled: int
    rank_ic: float | None


class Diagnostics(DiagnosticSummary):
    days: list[DiagnosticDay]
    folds: list[FoldDiagnostics]


class ModelReport(BaseModel):
    key: str    # "model", "baseline_1", …: what folds, scores and replays are stored under
    role: ModelRole
    label: str  # its name on screen: 主模型, 规则基线 1, …
    trainer: str
    params: dict[str, Any]
    failed_folds: list[int]
    diagnostics: Diagnostics


class TopixBenchmark(BaseModel):
    basis: str
    total_return: float


class PoolPeriod(BaseModel):
    date: date
    codes: int
    mean_return: float


class EqualWeightBenchmark(BaseModel):
    basis: str
    periods: list[PoolPeriod]
    total_return: float | None


class Benchmarks(BaseModel):
    topix_price: TopixBenchmark
    eligible_equal_weight: EqualWeightBenchmark


class FillRateOut(BaseModel):
    filled: int
    expired: int
    rate: float | None
    expired_reasons: dict[str, int]
    skipped_reasons: dict[str, int]


class Adv20Out(BaseModel):
    orders: int
    median: float | None
    p95: float | None
    max: float | None
    over_cap: int
    without_adv20: int
    cap: float | None


class ReplayMetrics(BaseModel):
    """Costs included; dividends and tax not."""
    sessions: int
    total_return: float
    topix_return: float
    excess_return: float
    annualised_return: float | None
    excess_annualised_return: float | None
    max_drawdown: float
    sharpe: float | None
    win_rate: float | None
    closed_positions: int
    average_holding_sessions: float | None
    annual_turnover: float | None
    trades: int
    fees: float
    cash: float
    average_cash_share: float | None
    realised_pnl: float
    unrealised_pnl: float
    fill_rate: FillRateOut
    adv20: Adv20Out


class PeriodOut(BaseModel):
    start: date
    end: date
    sessions: int
    net_return: float
    topix_return: float
    excess_return: float


class FoldPeriod(PeriodOut):
    fold: int


class YearPeriod(PeriodOut):
    year: int


class ReplaySummary(BaseModel):
    position: int
    model: str
    model_label: str               # the model's name on screen, as ModelReport.label
    scenario: Scenario
    extra_bps: float | None        # a stress scenario's addition to the base slippage
    costs: ExperimentCosts
    metrics: ReplayMetrics
    folds: list[FoldPeriod | None]
    years: list[YearPeriod]


class EvidenceReason(BaseModel):
    code: str
    message: str


class Evidence(BaseModel):
    status: EvidenceStatus
    reasons: list[EvidenceReason]
    viewed_folds: list[int]


class ExperimentReport(BaseModel):
    contract_hash: str
    sessions: int
    decision_days: int
    read_from: date
    folds: list[FoldOut]
    models: list[ModelReport]
    benchmarks: Benchmarks
    stress_basis: str
    replays: list[ReplaySummary]
    evidence: Evidence
    warnings: list[str]
    timings: dict[str, Any]


class ArtifactOut(BaseModel):
    trainer: str
    params: dict[str, Any]
    state: dict[str, Any]
    train_cutoff: date
    samples: int


class FoldResultOut(BaseModel):
    model: str
    fold: int
    train_from: date
    train_to: date
    test_from: date
    test_to: date
    samples: int
    seconds: float
    artifact: ArtifactOut | None  # None when the fold failed
    artifact_hash: str | None
    error: str | None


class DataSourceRead(BaseModel):
    kind: Literal["daily_bars", "segment_periods", "topix", "trading_calendar"]
    name: str
    start: date | None    # the first day it covered
    end: date | None      # the last
    rows: int
    detail: str           # what the rows count
    available_from: str   # when a row of it may be used for a decision


class DataRead(BaseModel):
    """What one attempt read and when: not when each row first became known
    — the database keeps no such time (ADR-0001) — only this read."""
    observed_at: str      # when the attempt read the market data, UTC
    note: str
    sources: list[DataSourceRead]


class ExperimentSummary(BaseModel):
    id: str
    name: str
    status: RunStatus
    created_at: str
    finished_at: str | None
    retry_of: str | None
    error: str | None
    error_code: FailureKind | None
    contract_hash: str
    evidence_status: EvidenceStatus | None
    test_from: date
    test_to: date
    trainer: str
    baselines: list[str]
    source_account_id: int | None


class ExperimentDetail(BaseModel):
    id: str
    name: str
    status: RunStatus
    created_at: str
    finished_at: str | None
    retry_of: str | None
    retried_by: list[str]
    progress: dict[str, Any]
    input_fingerprint: dict[str, Any] | None
    code_version: str
    error: str | None
    error_code: FailureKind | None
    data_read: DataRead | None  # None until the attempt has read the data
    contract: ExperimentContract
    contract_hash: str
    evidence_status: EvidenceStatus | None
    report: ExperimentReport | None
    fold_results: list[FoldResultOut]


class ExperimentHistory(BaseModel):
    total: int
    page: int
    page_size: int
    experiments: list[ExperimentSummary]


# --- one replay -----------------------------------------------------------------

class ReplayNavPoint(NavPointOut):
    cash: float


class ReplayResult(BaseModel):
    nav: list[ReplayNavPoint]
    holdings: list[ResearchHolding]
    pending: list[OrderOut]
    warnings: list[str]
    metrics: ReplayMetrics
    folds: list[FoldPeriod | None]
    years: list[YearPeriod]


class ReplayDetail(BaseModel):
    position: int
    model: str
    scenario: Scenario
    costs: ExperimentCosts
    result: ReplayResult


class ExperimentOrders(BaseModel):
    total: int
    page: int
    page_size: int
    orders: list[OrderOut]


class HoldingDecision(BaseModel):
    code: str
    disposition: str | None  # None: no signal that day (no tradable bar)
    reason_codes: list[str]
    score: float | None


class DayOrder(BaseModel):
    sequence: int
    kind: str
    code: str
    execution_date: date
    planned_quantity: int
    priority: float | None
    reason_codes: list[str]
    capped: str | None
    replaces: int | None
    status: str  # as it ended: filled / expired / skipped / pending
    outcome_reason: str | None


class DayExecution(BaseModel):
    sequence: int
    kind: str
    code: str
    signal_date: date
    status: str
    outcome_reason: str | None
    filled_quantity: int
    fill_price: float | None
    fees: float
    cash_delta: float


class TargetLine(BaseModel):
    code: str
    quantity: int


class DayConstraints(BaseModel):
    skipped: dict[str, int]
    adv20_capped: int
    ranked_out: int
    unplaced_candidates: int


class RankedScore(BaseModel):
    code: str
    score: float
    rank: int


class DayRecord(BaseModel):
    """One replayed session: the holdings' dispositions that morning's close,
    the orders planned (as they ended), what filled or expired at its open,
    the holdings the plan aims at, those held at the close, cash and NAV."""
    date: date
    decision_day: bool
    model_available: bool | None  # None on a day that is not a decision day
    fold: int | None
    universe: int
    scored: int
    holdings_decisions: list[HoldingDecision]
    candidates: int
    orders: list[DayOrder]
    executions: list[DayExecution]
    target: list[TargetLine]
    holdings: list[ResearchHolding]
    cash: float
    nav: float
    constraints: DayConstraints
    top_scores: list[RankedScore]


class ExperimentDays(BaseModel):
    total: int
    page: int
    page_size: int
    days: list[DayRecord]


class DayScores(BaseModel):
    model: str
    as_of: date
    fold: int
    artifact_hash: str
    scores: list[RankedScore]


# --- routes ---------------------------------------------------------------------

@router.get("/defaults")
def defaults(request: Request) -> ExperimentDefaults:
    return ExperimentDefaults(
        defaults=dict(DEFAULTS), trainers={name: dict(params) for name, params in TRAINER_DEFAULTS.items()},
        supported_actions=list(SUPPORTED_ACTIONS), unsupported_actions=list(UNSUPPORTED_ACTIONS),
        task=TaskOut(**TASK), features=FeaturesOut(version=FEATURES_V1, names=list(FEATURE_NAMES)),
        viewed_through=request.app.state.model_experiments.viewed_through())


@router.post("", status_code=202, responses=ERRORS)
def submit(request: Request, body: ExperimentIn) -> ExperimentAccepted:
    experiment_id = call_service(lambda: request.app.state.model_experiments.submit(
        body.model_dump(mode="json", exclude={"request_key"}), str(body.request_key)))
    return ExperimentAccepted(id=experiment_id)


@router.get("")
def history(request: Request, page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100)) -> ExperimentHistory:
    return request.app.state.model_experiments.history(page, page_size)


@router.get("/{experiment_id}", responses=ERRORS)
def detail(request: Request, experiment_id: str) -> ExperimentDetail:
    return call_service(lambda: request.app.state.model_experiments.get(experiment_id))


@router.post("/{experiment_id}/retry", status_code=202, responses=ERRORS)
def retry(request: Request, experiment_id: str, body: ExperimentRetryIn) -> ExperimentAccepted:
    new_id = call_service(lambda: request.app.state.model_experiments.submit(
        {}, str(body.request_key), retry_of=experiment_id))
    return ExperimentAccepted(id=new_id)


@router.get("/{experiment_id}/replays/{position}", responses=ERRORS)
def replay(request: Request, experiment_id: str, position: int) -> ReplayDetail:
    return call_service(lambda: request.app.state.model_experiments.replay(experiment_id, position))


@router.get("/{experiment_id}/replays/{position}/orders", responses=ERRORS)
def orders(request: Request, experiment_id: str, position: int, page: int = Query(1, ge=1),
           page_size: int = Query(50, ge=1, le=200)) -> ExperimentOrders:
    return call_service(lambda: request.app.state.model_experiments.orders(experiment_id, position, page, page_size))


@router.get("/{experiment_id}/replays/{position}/days", responses=ERRORS)
def days(request: Request, experiment_id: str, position: int, page: int = Query(1, ge=1),
         page_size: int = Query(20, ge=1, le=100), decision_only: bool = False) -> ExperimentDays:
    return call_service(lambda: request.app.state.model_experiments.days(
        experiment_id, position, page, page_size, decision_only=decision_only))


@router.get("/{experiment_id}/scores/{model}/{day}", responses=ERRORS)
def scores(request: Request, experiment_id: str, model: str, day: date) -> DayScores:
    return call_service(lambda: request.app.state.model_experiments.scores(experiment_id, model, day))
