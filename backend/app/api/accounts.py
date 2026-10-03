"""`/api/accounts…` and `/api/strategies` — the account pages. Handlers
only translate (spec A.6): the rules are behind `Accounts`."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.accounts import AccountSpec, Costs, PortfolioRules, strategy_choices
from app.api.schemas import (
    AccountCreated, AccountDetailOut, AccountIn, AccountSummaryOut, FiguresOut, HoldingOut, NavPointOut, OrderOut,
    OrdersPageOut, Refusal, StrategyOut, SuggestedRulesOut, WarmupFollowsOut,
)
from app.jobs import JobsBusy
from app.runtime import advance_job

router = APIRouter(prefix="/api", tags=["accounts"])

NOT_FOUND = {404: {"model": Refusal, "description": "没有这个账户"}}


@router.get("/strategies")
def strategies() -> list[StrategyOut]:
    """Each strategy's parameters with their defaults, the universe rule it
    buys under and the codes that rule names, how its warm-up follows its
    window, and the portfolio rules suggested for it — for the new-account
    and signal pages."""
    return [
        StrategyOut(
            name=choice.strategy.name, defaults=dict(choice.strategy.defaults),
            universe_rule=choice.strategy.universe_rule, pool_codes=list(choice.pool_codes),
            warmup_follows=(WarmupFollowsOut(parameter=follows.parameter, extra=follows.extra)
                            if (follows := choice.strategy.warmup_follows) else None),
            suggested_rules=SuggestedRulesOut(max_positions=choice.suggested_rules.max_positions,
                                              max_weight=float(choice.suggested_rules.max_weight),
                                              cash_floor=float(choice.suggested_rules.cash_floor)),
        )
        for choice in strategy_choices()
    ]


@router.get("/accounts")
def accounts(request: Request) -> list[AccountSummaryOut]:
    return [AccountSummaryOut(**asdict(summary)) for summary in request.app.state.accounts.list()]


@router.post("/accounts", status_code=201, responses={422: {"model": Refusal, "description": "参数不合规"}})
def create(request: Request, body: AccountIn) -> AccountCreated:
    """Creates the account and queues its backtest at once (spec §8)."""
    spec = AccountSpec(
        name=body.name, strategy=body.strategy, start_date=body.start_date, strategy_params=body.strategy_params,
        initial_cash=_decimal(body.initial_cash),
        rules=PortfolioRules(max_positions=body.max_positions, max_weight=_decimal(body.max_weight),
                             cash_floor=_decimal(body.cash_floor)),
        costs=Costs(commission_rate=_decimal(body.commission_rate), commission_min=_decimal(body.commission_min),
                    slippage=_decimal(body.slippage)),
    )
    try:
        account_id = request.app.state.accounts.create(spec)
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from None
    try:
        job_id = request.app.state.jobs.submit(advance_job(request.app.state.accounts, account_id))
    except JobsBusy as busy:
        return AccountCreated(id=account_id, advance_job_id=None, advance_refused=str(busy))
    return AccountCreated(id=account_id, advance_job_id=job_id, advance_refused=None)


@router.get("/accounts/{account_id}", responses=NOT_FOUND)
def detail(request: Request, account_id: int) -> AccountDetailOut:
    report = _report(request, account_id)
    account = report.account
    names = _names(request, [h.code for h in report.holdings] + [r.code for r in report.pending])
    return AccountDetailOut(
        id=account["id"], name=account["name"], strategy=account["strategy"],
        strategy_params=account["strategy_params"],
        rules={key: float(value) for key, value in account["portfolio_rules"].items()},
        costs={key: float(value) for key, value in account["costs"].items()},
        start_date=account["start_date"], advanced_through=account["advanced_through"], status=account["status"],
        backtest_data_mark=account["backtest_data_mark"],
        figures=None if report.figures is None else FiguresOut(
            **{name: getattr(report.figures, name) for name in FiguresOut.model_fields}),
        holdings=[HoldingOut(code=h.code, name=names.get(h.code), quantity=h.quantity, opened_on=h.opened_on,
                             cost=float(h.cost), close=float(h.close), value=float(h.value))
                  for h in report.holdings],
        pending=[_order(record, names) for record in report.pending],
    )


@router.get("/accounts/{account_id}/nav", responses=NOT_FOUND)
def nav(request: Request, account_id: int) -> list[NavPointOut]:
    """The net asset value and TOPIX, both from 1 on the first session, and
    how far the NAV stands below its highest so far."""
    report = _report(request, account_id)
    if report.figures is None:
        return []
    values = report.nav.astype(float)
    drawdown = 1 - values / values.cummax()
    return [NavPointOut(date=day, nav=values[day], nav_curve=report.figures.nav_curve[day],
                        topix_curve=report.figures.topix_curve[day], drawdown=drawdown[day])
            for day in values.index]


@router.get("/accounts/{account_id}/orders", responses=NOT_FOUND)
def orders(request: Request, account_id: int, page: int = Query(1, ge=1),
           page_size: int = Query(50, ge=1, le=200),
           kind: Literal["all", "buy", "sell", "skipped", "events"] = "all") -> OrdersPageOut:
    """The orders and account events so far, newest first; tomorrow's orders
    are on the account itself, as `pending`."""
    history = [record for record in reversed(_report(request, account_id).orders) if record.status != "pending"]
    counts = {"all": len(history), "buy": 0, "sell": 0, "skipped": 0, "events": 0}
    for record in history:
        counts[_group(record)] += 1
    chosen = history if kind == "all" else [record for record in history if _group(record) == kind]
    shown = chosen[(page - 1) * page_size:page * page_size]
    names = _names(request, [record.code for record in shown])
    return OrdersPageOut(total=len(chosen), page=page, page_size=page_size, counts=counts,
                         orders=[_order(record, names) for record in shown])


@router.post("/accounts/{account_id}/stop", status_code=204, responses=NOT_FOUND)
def stop(request: Request, account_id: int) -> None:
    _found(lambda: request.app.state.accounts.stop(account_id))


@router.delete("/accounts/{account_id}", status_code=204, responses=NOT_FOUND)
def delete(request: Request, account_id: int) -> None:
    _found(lambda: request.app.state.accounts.delete(account_id))


def _report(request: Request, account_id: int):
    return _found(lambda: request.app.state.accounts.report(account_id))


def _found(call):
    try:
        return call()
    except LookupError as missing:
        raise HTTPException(status_code=404, detail=str(missing)) from None


def _group(record) -> str:
    if record.status == "skipped":
        return "skipped"
    return record.kind if record.kind in ("buy", "sell") else "events"


def _names(request: Request, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    return {found.code: found.name for found in request.app.state.market.instruments(codes=sorted(set(codes)))}


def _order(record, names: dict[str, str]) -> OrderOut:
    return OrderOut(**{
        **asdict(record),
        "name": names.get(record.code),
        "fill_price": None if record.fill_price is None else float(record.fill_price),
        "fees": float(record.fees),
        "cash_delta": float(record.cash_delta),
    })


def _decimal(value: float) -> Decimal:
    """Through its shortest text, so 0.1 stays 0.1 and not 0.1000000000000000055…"""
    return Decimal(repr(value))
