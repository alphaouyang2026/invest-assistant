"""`/api/signals` and `/api/instruments/*` — the signal page and the
security page. Handlers only translate (spec A.6): the assembly is
`entry_candidates` and `history`."""

from __future__ import annotations

import math
from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.schemas import (
    BarOut, CandidateOut, InstrumentOut, LinePoint, PlotOut, Refusal, SecurityBarsOut, SignalsOut,
)
from app.market_data import CLOSE, HIGH, LOW, OPEN, VOLUME
from app.strategies import build_strategy, entry_candidates, history

router = APIRouter(prefix="/api", tags=["signals"])

NOT_FOUND = {404: {"model": Refusal, "description": "没有这个策略，或还没有行情"}}


@router.get("/signals", responses=NOT_FOUND)
def signals(request: Request, strategy: str, date: Date | None = None) -> SignalsOut:
    market = request.app.state.market
    chosen = _strategy(strategy)
    day = date or _latest(request)
    return SignalsOut(
        strategy=strategy,
        date=day,
        candidates=[
            CandidateOut(code=c.instrument.code, name=c.instrument.name, market=c.instrument.market,
                         priority=c.signal.priority, reason_codes=list(c.signal.reason_codes))
            for c in entry_candidates(market, chosen, day)
        ],
    )


@router.get("/instruments")
def instruments(request: Request, q: str) -> list[InstrumentOut]:
    return [InstrumentOut(**vars(found)) for found in request.app.state.market.instruments(query=q)]


@router.get("/instruments/{code}/bars", responses=NOT_FOUND)
def bars(
    request: Request,
    code: str,
    strategy: str,
    start: Date | None = Query(None, alias="from"),
    end: Date | None = Query(None, alias="to"),
) -> SecurityBarsOut:
    """Defaults: up to the latest session, a year back."""
    end = end or _latest(request)
    start = start or end - timedelta(days=365)
    chosen = _strategy(strategy)
    past = history(request.app.state.market, chosen, code, start, end)
    prices = past.frame.data.xs(code, level="code") if len(past.frame.data) else past.frame.data
    return SecurityBarsOut(
        code=code,
        bars=[BarOut(date=day, open=_number(row[OPEN]), high=_number(row[HIGH]), low=_number(row[LOW]),
                     close=_number(row[CLOSE]), volume=_number(row[VOLUME])) for day, row in prices.iterrows()],
        plots=[PlotOut(indicator=plot.indicator, pane=plot.pane) for plot in chosen.plots],
        lines={name: [LinePoint(date=day, value=_number(value)) for day, value in past.indicators[name].items()]
               for name in past.indicators.columns},
        entries=past.entries,
    )


def _number(value) -> float | None:
    return None if value is None or math.isnan(value) else float(value)


def _strategy(name: str):
    try:
        return build_strategy(name, {})
    except ValueError as unknown:
        raise HTTPException(status_code=404, detail=str(unknown)) from None


def _latest(request: Request) -> Date:
    latest = request.app.state.market.overview().latest_date
    if latest is None:
        raise HTTPException(status_code=404, detail="还没有行情，先同步")
    return latest
