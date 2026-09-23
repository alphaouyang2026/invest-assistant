"""The J-Quants HTTP adapter, against a scripted server — never the network.

What the rest of the system relies on: the key goes in `x-api-key`, pages
are followed to the end, requests are spaced and retried by the Light
plan's rules, and what comes back is parsed records rather than JSON.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.market_data.jquants import (
    BarRecord,
    CalendarDay,
    HttpJQuantsClient,
    IndexBar,
    JQuantsError,
    RosterEntry,
)


class FakeClock:
    """`monotonic` and `sleep` in one: sleeping moves the clock, so the
    adapter's pacing is observable as the list of sleeps it asked for."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def client_for(handler, clock: FakeClock | None = None) -> HttpJQuantsClient:
    clock = clock or FakeClock()
    return HttpJQuantsClient(
        "test-key",
        transport=httpx.MockTransport(handler),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_daily_bars_for_a_date_come_back_as_parsed_records() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{
            "Date": "2026-09-18", "Code": "72030",
            "O": 2800.5, "H": 2850, "L": 2790, "C": 2840,
            "UL": "0", "LL": "1", "Vo": 1200300, "Va": 3400000000,
            "AdjFactor": 1.0, "AdjO": 2800.5, "AdjH": 2850, "AdjL": 2790,
            "AdjC": 2840, "AdjVo": 1200300, "ExRT": "",
        }]})

    bars = client_for(handler).daily_bars_on(date(2026, 9, 18))

    assert seen[0].headers["x-api-key"] == "test-key"
    assert seen[0].url.path.endswith("/equities/bars/daily")
    assert seen[0].url.params["date"] == "2026-09-18"
    assert bars == [BarRecord(
        code="72030", date=date(2026, 9, 18),
        open=Decimal("2800.5"), high=Decimal("2850"), low=Decimal("2790"), close=Decimal("2840"),
        volume=Decimal("1200300"), turnover=Decimal("3400000000"),
        adjustment_factor=Decimal("1.0"), ex_rights_type=None,
        upper_limit_hit=False, lower_limit_hit=True,
        adjusted_close=Decimal("2840"),
    )]


def bar_row(code: str, day: str = "2026-09-18", **fields) -> dict:
    return {"Date": day, "Code": code, "O": 100, "H": 100, "L": 100, "C": 100,
            "UL": "0", "LL": "0", "Vo": 10, "Va": 1000, "AdjFactor": 1, "AdjC": 100} | fields


def test_pages_are_followed_until_there_is_no_pagination_key() -> None:
    keys_sent: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.params.get("pagination_key")
        keys_sent.append(key)
        if key is None:
            return httpx.Response(200, json={"data": [bar_row("13010")], "pagination_key": "p2"})
        if key == "p2":
            return httpx.Response(200, json={"data": [bar_row("13020")], "pagination_key": "p3"})
        return httpx.Response(200, json={"data": [bar_row("13030")]})

    bars = client_for(handler).daily_bars_on(date(2026, 9, 18))

    assert keys_sent == [None, "p2", "p3"]
    assert [bar.code for bar in bars] == ["13010", "13020", "13030"]


def test_requests_are_spaced_at_least_1_1_seconds_apart() -> None:
    """Light allows 60 requests a minute; 1.1 s keeps a margin under it."""
    clock = FakeClock()
    request_times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_times.append(clock.now)
        clock.now += 0.3  # the server takes a while to answer
        page = request.url.params.get("pagination_key")
        return httpx.Response(200, json={"data": [], **({} if page else {"pagination_key": "p2"})})

    client = client_for(handler, clock)
    client.daily_bars_on(date(2026, 9, 18))
    clock.now += 5.0  # a long pause needs no extra wait
    client.daily_bars_on(date(2026, 9, 19))

    gaps = [round(later - earlier, 6) for earlier, later in zip(request_times, request_times[1:])]
    assert gaps == [1.1, 5.3, 1.1]


def scripted(*responses: httpx.Response | Exception):
    """A handler that answers with each response (or raises each error) in turn."""
    queue = list(responses)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    handler.calls = calls
    return handler


OK = httpx.Response(200, json={"data": [bar_row("13010")]})


def test_a_429_waits_two_minutes_and_retries() -> None:
    """J-Quants sends no Retry-After, and the rolling minute counts the
    rejected request too, so anything shorter risks another 429."""
    clock = FakeClock()
    handler = scripted(httpx.Response(429), OK)

    bars = client_for(handler, clock).daily_bars_on(date(2026, 9, 18))

    assert [bar.code for bar in bars] == ["13010"]
    assert clock.sleeps == [120.0]


def test_timeouts_network_errors_and_5xx_back_off_5_10_20_seconds() -> None:
    clock = FakeClock()
    handler = scripted(
        httpx.Response(503),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
        OK,
    )

    bars = client_for(handler, clock).daily_bars_on(date(2026, 9, 18))

    assert [bar.code for bar in bars] == ["13010"]
    assert clock.sleeps == [5.0, 10.0, 20.0]


def test_the_fifth_failure_gives_up_with_an_error_naming_the_endpoint() -> None:
    clock = FakeClock()
    handler = scripted(*[httpx.Response(500)] * 5)

    with pytest.raises(JQuantsError) as failure:
        client_for(handler, clock).daily_bars_on(date(2026, 9, 18))

    assert len(handler.calls) == 5
    assert clock.sleeps == [5.0, 10.0, 20.0, 40.0]
    assert "/equities/bars/daily" in str(failure.value)


def answering(data: list[dict]):
    handler = scripted(httpx.Response(200, json={"data": data}))
    return handler


def test_one_securitys_bars_over_a_range() -> None:
    handler = answering([bar_row("72030", "2026-09-17", ExRT="1", AdjFactor=0.5, AdjC=50.0)])

    bars = client_for(handler).daily_bars_for("72030", date(2026, 6, 1), date(2026, 9, 17))

    request = handler.calls[0]
    assert request.url.path.endswith("/equities/bars/daily")
    assert dict(request.url.params) == {"code": "72030", "from": "2026-06-01", "to": "2026-09-17"}
    assert (bars[0].adjustment_factor, bars[0].ex_rights_type, bars[0].adjusted_close) == (
        Decimal("0.5"), 1, Decimal("50.0"),
    )


def test_the_roster_on_a_date() -> None:
    handler = answering([{
        "Date": "2026-09-18", "Code": "72030", "CoName": "トヨタ自動車", "CoNameEn": "TOYOTA MOTOR",
        "S17": "6", "S17Nm": "自動車・輸送機", "S33": "3700", "S33Nm": "輸送用機器",
        "ScaleCat": "TOPIX Core30", "Mkt": "0111", "MktNm": "プライム",
        "Mrgn": "2", "MrgnNm": "貸借", "ProdCat": "011",
    }])

    roster = client_for(handler).roster_on(date(2026, 9, 18))

    assert handler.calls[0].url.path.endswith("/equities/master")
    assert handler.calls[0].url.params["date"] == "2026-09-18"
    assert roster == [RosterEntry(
        code="72030", name="トヨタ自動車", name_en="TOYOTA MOTOR", scale_category="TOPIX Core30",
        market_code="0111", product_category="011", sector33="3700",
    )]


def test_the_trading_calendar() -> None:
    handler = answering([
        {"Date": "2026-09-21", "HolDiv": "0"},
        {"Date": "2026-09-24", "HolDiv": "1"},
    ])

    days = client_for(handler).calendar()

    assert handler.calls[0].url.path.endswith("/markets/calendar")
    assert days == [CalendarDay(date(2026, 9, 21), 0), CalendarDay(date(2026, 9, 24), 1)]


def test_topix_over_a_range() -> None:
    handler = answering([{"Date": "2026-09-18", "O": 2700.12, "H": 2710.5, "L": 2690, "C": 2705.33}])

    bars = client_for(handler).topix(date(2026, 9, 1), date(2026, 9, 18))

    request = handler.calls[0]
    assert request.url.path.endswith("/indices/bars/daily/topix")
    assert dict(request.url.params) == {"from": "2026-09-01", "to": "2026-09-18"}
    assert bars == [IndexBar(
        date(2026, 9, 18), Decimal("2700.12"), Decimal("2710.5"), Decimal("2690"), Decimal("2705.33"),
    )]
