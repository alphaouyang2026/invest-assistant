"""Manual-range research HTTP translation; no backtesting in GET handlers."""
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.schemas import NavPointOut, OrderOut, Refusal
from app.jobs import JobsBusy

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchIn(BaseModel):
    request_key: UUID
    source_account_id: int = Field(gt=0)
    start_date: date
    end_date: date
    entry_above: float = Field(default=0.5, ge=-1, le=1, allow_inf_nan=False)
    exit_below: float = Field(default=-0.1, ge=-1, le=1, allow_inf_nan=False)


class ResearchRetryIn(BaseModel):
    request_key: UUID


class ResearchAccepted(BaseModel):
    id: str


class ResearchConfig(BaseModel):
    name: str
    strategy: str
    strategy_params: dict[str, Any]
    portfolio_rules: dict[str, Any]
    costs: dict[str, str]
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
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    finished_at: str | None
    progress: dict[str, Any]
    input_identity: dict[str, Any] | None
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


def _call(call):
    try:
        return call()
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except JobsBusy as error:
        raise HTTPException(409, str(error)) from None


ERRORS = {code: {"model": Refusal} for code in (404, 409, 422)}


@router.get("/sources")
def sources(request: Request) -> list[ResearchSource]:
    return request.app.state.research.sources()


@router.post("/runs", status_code=202, responses=ERRORS)
def submit(request: Request, body: ResearchIn) -> ResearchAccepted:
    run_id = _call(lambda: request.app.state.research.submit(
        body.model_dump(mode="json", exclude={"request_key"}), str(body.request_key)))
    return ResearchAccepted(id=run_id)


@router.get("/runs")
def history(request: Request, page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100)) -> ResearchHistory:
    return request.app.state.research.history(page, page_size)


@router.get("/runs/{run_id}", responses=ERRORS)
def detail(request: Request, run_id: str) -> ResearchDetail:
    return _call(lambda: request.app.state.research.get(run_id))


@router.get("/runs/{run_id}/orders", responses=ERRORS)
def orders(request: Request, run_id: str, page: int = Query(1, ge=1),
           page_size: int = Query(50, ge=1, le=200)) -> ResearchOrders:
    return _call(lambda: request.app.state.research.orders(run_id, page, page_size))


@router.post("/runs/{run_id}/retry", status_code=202, responses=ERRORS)
def retry(request: Request, run_id: str, body: ResearchRetryIn) -> ResearchAccepted:
    new_id = _call(lambda: request.app.state.research.submit({}, str(body.request_key), retry_of=run_id))
    return ResearchAccepted(id=new_id)
