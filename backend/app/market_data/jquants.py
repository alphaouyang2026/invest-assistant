"""The J-Quants seam: what the market data module asks J-Quants for.

`JQuantsClient` is the interface; `HttpJQuantsClient` talks to the V2 API,
and the tests have an in-memory one. Either way the caller gets parsed
records — prices as `Decimal`, dates as `date` — never JSON.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

import httpx


class JQuantsError(RuntimeError):
    """J-Quants could not be reached or refused the request, after retries."""


@dataclass(frozen=True)
class BarRecord:
    """One security on one date, as J-Quants reports it (unadjusted).

    `adjusted_close` is J-Quants' own `AdjC`. It is not stored (ADR-0003);
    the split check compares it against the research price computed here.
    """

    code: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    turnover: Decimal | None
    adjustment_factor: Decimal
    ex_rights_type: int | None
    upper_limit_hit: bool
    lower_limit_hit: bool
    adjusted_close: Decimal | None


@dataclass(frozen=True)
class RosterEntry:
    """One security on the listed-issues roster (`/equities/master`)."""

    code: str
    name: str
    name_en: str
    scale_category: str
    market_code: str
    product_category: str
    sector33: str


@dataclass(frozen=True)
class CalendarDay:
    date: date
    holiday_division: int  # HolDiv: 0 closed, 1 open, 2 half day, 3 closed with holiday trading


@dataclass(frozen=True)
class IndexBar:
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None


class JQuantsClient(Protocol):
    def daily_bars_on(self, day: date) -> list[BarRecord]: ...
    def daily_bars_for(self, code: str, start: date, end: date) -> list[BarRecord]: ...
    def roster_on(self, day: date) -> list[RosterEntry]: ...
    def calendar(self) -> list[CalendarDay]: ...
    def topix(self, start: date, end: date) -> list[IndexBar]: ...


class HttpJQuantsClient:
    BASE_URL = "https://api.jquants.com/v2"
    # Light allows 60 requests per rolling minute, rejected ones included;
    # spacing every request (retries too) keeps a margin under that.
    MIN_INTERVAL_SECONDS = 1.1
    # A 429 carries no Retry-After; two minutes lets the rolling window,
    # which counted the rejected request too, fully drain.
    RATE_LIMITED_WAIT_SECONDS = 120.0
    # Timeouts, network errors and 5xx: wait 5, 10, 20, 40 s — five attempts.
    MAX_ATTEMPTS = 5
    FIRST_BACKOFF_SECONDS = 5.0

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=self.BASE_URL,
            headers={"x-api-key": api_key},
            timeout=httpx.Timeout(60.0, connect=10.0),
            transport=transport,
        )
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None

    def daily_bars_on(self, day: date) -> list[BarRecord]:
        return [_bar(row) for row in self._fetch("/equities/bars/daily", {"date": day.isoformat()})]

    def daily_bars_for(self, code: str, start: date, end: date) -> list[BarRecord]:
        params = {"code": code, "from": start.isoformat(), "to": end.isoformat()}
        return [_bar(row) for row in self._fetch("/equities/bars/daily", params)]

    def roster_on(self, day: date) -> list[RosterEntry]:
        return [_roster_entry(row) for row in self._fetch("/equities/master", {"date": day.isoformat()})]

    def calendar(self) -> list[CalendarDay]:
        return [
            CalendarDay(date.fromisoformat(row["Date"]), int(row["HolDiv"]))
            for row in self._fetch("/markets/calendar", {})
        ]

    def topix(self, start: date, end: date) -> list[IndexBar]:
        params = {"from": start.isoformat(), "to": end.isoformat()}
        return [
            IndexBar(
                date.fromisoformat(row["Date"]),
                _decimal(row.get("O")), _decimal(row.get("H")), _decimal(row.get("L")), _decimal(row.get("C")),
            )
            for row in self._fetch("/indices/bars/daily/topix", params)
        ]

    def _fetch(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """Every row across every page."""
        rows: list[dict[str, Any]] = []
        pagination_key: str | None = None
        while True:
            page_params = params if pagination_key is None else params | {"pagination_key": pagination_key}
            payload = self._get(path, page_params)
            rows.extend(payload["data"])
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                return rows

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        failures = 0
        while True:
            self._wait_for_turn()
            try:
                response = self._http.get(path, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                problem: str = type(error).__name__
            else:
                if response.status_code == 429:
                    self._sleep(self.RATE_LIMITED_WAIT_SECONDS)
                    continue
                if response.status_code < 400:
                    return json.loads(response.content, parse_float=Decimal)
                if response.status_code < 500:
                    raise JQuantsError(f"J-Quants {path} 返回 HTTP {response.status_code}")
                problem = f"HTTP {response.status_code}"

            failures += 1
            if failures == self.MAX_ATTEMPTS:
                raise JQuantsError(f"J-Quants {path} 重试 {failures} 次仍失败（{problem}）")
            self._sleep(self.FIRST_BACKOFF_SECONDS * 2 ** (failures - 1))

    def _wait_for_turn(self) -> None:
        if self._last_request_at is not None:
            remaining = self.MIN_INTERVAL_SECONDS - (self._monotonic() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()


def _decimal(value: Any) -> Decimal | None:
    # Floats arrive as Decimal already (`parse_float`); integers do not.
    return None if value is None or value == "" else Decimal(value)


def _bar(row: dict[str, Any]) -> BarRecord:
    ex_rights = row.get("ExRT")
    return BarRecord(
        code=row["Code"],
        date=date.fromisoformat(row["Date"]),
        open=_decimal(row.get("O")),
        high=_decimal(row.get("H")),
        low=_decimal(row.get("L")),
        close=_decimal(row.get("C")),
        volume=_decimal(row.get("Vo")),
        turnover=_decimal(row.get("Va")),
        adjustment_factor=_decimal(row.get("AdjFactor")) or Decimal(1),
        ex_rights_type=int(ex_rights) if ex_rights else None,
        upper_limit_hit=row.get("UL") == "1",
        lower_limit_hit=row.get("LL") == "1",
        adjusted_close=_decimal(row.get("AdjC")),
    )


def _roster_entry(row: dict[str, Any]) -> RosterEntry:
    return RosterEntry(
        code=row["Code"],
        name=row.get("CoName") or "",
        name_en=row.get("CoNameEn") or "",
        scale_category=row.get("ScaleCat") or "",
        market_code=row["Mkt"],
        product_category=row.get("ProdCat") or "",
        sector33=row.get("S33") or "",
    )
