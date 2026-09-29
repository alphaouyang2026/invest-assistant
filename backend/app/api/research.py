"""Research run HTTP translation; no backtesting in GET handlers. Also
what the batch and discovery routes share with it: the error mapping, the
threshold fields and the frozen configuration."""
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.accounts.research import RESEARCH_STRATEGY
from app.accounts.research_batches import StaleInput
from app.accounts.research_jobs import RunStatus
from app.api.schemas import NavPointOut, OrderOut, Refusal
from app.jobs import JobsBusy
from app.strategies import STRATEGY_DEFAULTS

router = APIRouter(prefix="/api/research", tags=["research"])

T = TypeVar("T")


def call_service(call: Callable[[], T]) -> T:
    """A research service's refusals as HTTP answers."""
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


ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": Refusal} for code in (404, 409, 422)}
STALE_ERRORS: dict[int | str, dict[str, Any]] = {**ERRORS, 412: {"model": Refusal}}
_DEFAULTS = STRATEGY_DEFAULTS[RESEARCH_STRATEGY]


class Thresholds(BaseModel):
    """One fixed pair of thresholds on a source account's configuration."""
    source_account_id: int = Field(gt=0)
    entry_above: float = Field(default=_DEFAULTS["entry_above"], ge=-1, le=1, allow_inf_nan=False)
    exit_below: float = Field(default=_DEFAULTS["exit_below"], ge=-1, le=1, allow_inf_nan=False)


class ResearchIn(Thresholds):
    request_key: UUID
    start_date: date
    end_date: date


class ResearchRetryIn(BaseModel):
    request_key: UUID


class ResearchAccepted(BaseModel):
    id: str


class FrozenConfig(BaseModel):
    """The source's configuration as it was when the research was accepted."""
    name: str
    strategy: str
    strategy_params: dict[str, Any]
    portfolio_rules: dict[str, Any]
    costs: dict[str, str]


class ResearchConfig(FrozenConfig):
    start_date: date
    end_date: date | None = None
    source_account_id: int | None = None


class ResearchSource(BaseModel):
    id: int
    name: str
    config: ResearchConfig


class ResearchHolding(BaseModel):
    code: str
    quantity: int
    opened_on: date
    cost: float
    close: float
    value: float


class ResearchResult(BaseModel):
    nav: list[NavPointOut]
    holdings: list[ResearchHolding]
    pending: list[OrderOut]
    warnings: list[str]
    total_return: float
    topix_return: float
    excess_return: float
    max_drawdown: float
    trades: int
    fees: float
    cash: float
    realised_pnl: float
    unrealised_pnl: float


class ResearchSummary(BaseModel):
    id: str
    config: ResearchConfig
    retry_of: str | None
    status: RunStatus
    created_at: str
    finished_at: str | None
    progress: dict[str, Any]
    input_fingerprint: dict[str, Any] | None
    code_version: str
    error: str | None


class ResearchDetail(ResearchSummary):
    result: ResearchResult | None


class ResearchHistory(BaseModel):
    total: int
    page: int
    page_size: int
    runs: list[ResearchSummary]


class ResearchOrders(BaseModel):
    total: int
    page: int
    page_size: int
    orders: list[OrderOut]


@router.get("/sources")
def sources(request: Request) -> list[ResearchSource]:
    return request.app.state.research_runs.sources()


@router.post("/runs", status_code=202, responses=ERRORS)
def submit(request: Request, body: ResearchIn) -> ResearchAccepted:
    run_id = call_service(lambda: request.app.state.research_runs.submit(
        body.model_dump(mode="json", exclude={"request_key"}), str(body.request_key)))
    return ResearchAccepted(id=run_id)


@router.get("/runs")
def history(request: Request, page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100)) -> ResearchHistory:
    return request.app.state.research_runs.history(page, page_size)


@router.get("/runs/{run_id}", responses=ERRORS)
def detail(request: Request, run_id: str) -> ResearchDetail:
    return call_service(lambda: request.app.state.research_runs.get(run_id))


@router.get("/runs/{run_id}/orders", responses=ERRORS)
def orders(request: Request, run_id: str, page: int = Query(1, ge=1),
           page_size: int = Query(50, ge=1, le=200)) -> ResearchOrders:
    return call_service(lambda: request.app.state.research_runs.orders(run_id, page, page_size))


@router.post("/runs/{run_id}/retry", status_code=202, responses=ERRORS)
def retry(request: Request, run_id: str, body: ResearchRetryIn) -> ResearchAccepted:
    new_id = call_service(lambda: request.app.state.research_runs.submit({}, str(body.request_key), retry_of=run_id))
    return ResearchAccepted(id=new_id)
