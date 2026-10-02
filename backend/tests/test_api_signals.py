"""The signal page's API: `/api/signals`, `/api/instruments` and
`/api/instruments/{code}/bars`.

Handlers only translate (spec A.6), so these check the shapes and the
wiring. A stand-in strategy is swapped in for `build_strategy`: the real
ones need a year of bars, and their rules are tested on their own.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.market_data import CLOSE, UniverseRule
from app.market_data.jquants import IndexBar
from app.strategies import Disposition, Plot, Signal
from tests.fakes import FakeJQuants, bar, listed

SESSIONS = [date(2026, 9, 1) + timedelta(days=n) for n in range(24)]
DAY = SESSIONS[-1]
LIQUID = Decimal("600000000")


class StandIn:
    """Holds 13010 on every session, ranked 0.42."""

    name = "stand_in"
    warmup_sessions = 3
    plots = (Plot("close", "price"), Plot("double", "separate"))
    universe_rule = UniverseRule.PRIME_COMMON_STOCK
    reference_series: tuple[str, ...] = ()

    def evaluate(self, frame, day, holdings):
        closes = frame.wide(CLOSE)
        return [
            Signal(code, Disposition.HOLD if code == "13010" else Disposition.STAY_OUT,
                   ("stand_in_reason",) if code == "13010" else (),
                   {"close": float(closes[code][day]), "double": 2 * float(closes[code][day])},
                   0.42 if code == "13010" else None)
            for code in closes.columns if day in closes.index
        ]


@pytest.fixture
def api(migrated_database, monkeypatch):
    asked = []

    def build(name, params):
        asked.append(name)
        if name != "stand_in":
            raise ValueError(f"没有这个策略：{name}")
        return StandIn()

    monkeypatch.setattr("app.api.signals.build_strategy", build)
    bars = {day: [bar("13010", day, str(100 + n), turnover=LIQUID), bar("13020", day, turnover=LIQUID)]
            for n, day in enumerate(SESSIONS)}
    fake = FakeJQuants(SESSIONS, bars=bars, roster=[listed("13010", name="トヨタ自動車"), listed("13020")])
    app = create_app(Settings(_env_file=None), client=fake, today=lambda: DAY)
    with TestClient(app) as client:
        app.state.market.sync()
        yield client


@pytest.fixture
def real_strategies(migrated_database):
    """The real strategies, on a market where 1306 is listed as an ETF
    (その他, 0109) beside a Prime stock."""
    bars = {day: [bar("13010", day, turnover=LIQUID), bar("13060", day, "3000", turnover=LIQUID)]
            for day in SESSIONS}
    roster = [listed("13010"), listed("13060", "0109", product="014", name="ＴＯＰＩＸ連動型上場投信")]
    fake = FakeJQuants(SESSIONS, bars=bars, roster=roster)
    app = create_app(Settings(_env_file=None), client=fake, today=lambda: DAY)
    with TestClient(app) as client:
        app.state.market.sync()
        yield client


TOPIX_SESSIONS = [date(2026, 1, 5) + timedelta(days=n) for n in range(203)]
# On its 200-close average of 100 until the last two sessions, then 102 and 104.
TOPIX_CLOSES = ["100"] * 201 + ["102", "104"]


@pytest.fixture
def topix_market(migrated_database):
    """The real strategies, with their default parameters, on 1306 at 3,000
    and TOPIX as above: a year of sessions, enough for a 200-close average."""
    bars = {day: [bar("13060", day, "3000", turnover=LIQUID)] for day in TOPIX_SESSIONS}
    roster = [listed("13060", "0109", product="014", name="ＴＯＰＩＸ連動型上場投信")]
    topix = [IndexBar(day, *[Decimal(close)] * 4) for day, close in zip(TOPIX_SESSIONS, TOPIX_CLOSES)]
    fake = FakeJQuants(TOPIX_SESSIONS, bars=bars, roster=roster, topix=topix)
    app = create_app(Settings(_env_file=None), client=fake, today=lambda: TOPIX_SESSIONS[-1])
    with TestClient(app) as client:
        app.state.market.sync()
        yield client


def test_the_moving_average_strategy_has_1306_as_its_candidate_or_none(topix_market) -> None:
    """On the latest session TOPIX closes at 104, over 1% above its average:
    1306. Two sessions earlier it sat on its average: nothing."""
    latest = topix_market.get("/api/signals", params={"strategy": "topix_ma_v1"}).json()
    on_the_average = topix_market.get("/api/signals", params={
        "strategy": "topix_ma_v1", "date": TOPIX_SESSIONS[-3].isoformat()}).json()

    [candidate] = latest["candidates"]
    assert (candidate["code"], candidate["market"], candidate["reason_codes"]) == ("13060", "0109", ["topix_above_ma"])
    assert candidate["priority"] == pytest.approx(104 / ((198 * 100 + 102 + 104) / 200) - 1)
    assert on_the_average["candidates"] == []


def test_1306s_bars_come_with_topix_and_its_average_and_the_days_it_would_have_been_bought(topix_market) -> None:
    days = [day.isoformat() for day in TOPIX_SESSIONS[-3:]]

    body = topix_market.get("/api/instruments/13060/bars",
                            params={"strategy": "topix_ma_v1", "from": days[0], "to": days[-1]}).json()

    assert [b["date"] for b in body["bars"]] == days and {b["close"] for b in body["bars"]} == {3000.0}
    assert body["plots"] == [{"indicator": "topix_close", "pane": "separate"},
                             {"indicator": "topix_ma", "pane": "separate"}]
    assert {name: [point["date"] for point in line] for name, line in body["lines"].items()} == {
        "topix_close": days, "topix_ma": days}
    assert [point["value"] for point in body["lines"]["topix_close"]] == [100.0, 102.0, 104.0]
    assert [point["value"] for point in body["lines"]["topix_ma"]] == pytest.approx([100.0, 100.01, 100.03])
    assert body["entries"] == days[1:]


def test_the_control_group_has_1306_as_its_entry_candidate(real_strategies) -> None:
    body = real_strategies.get("/api/signals", params={"strategy": "topix_buy_and_hold_v1"}).json()

    assert body["candidates"] == [
        {"code": "13060", "name": "ＴＯＰＩＸ連動型上場投信", "market": "0109", "priority": 1.0,
         "reason_codes": ["always_hold"]},
    ]


def test_signals_list_the_entry_candidates_of_the_latest_session_by_default(api) -> None:
    body = api.get("/api/signals", params={"strategy": "stand_in"}).json()

    assert body == {
        "strategy": "stand_in",
        "date": DAY.isoformat(),
        "candidates": [
            {"code": "13010", "name": "トヨタ自動車", "market": "0111", "priority": 0.42, "reason_codes": ["stand_in_reason"]},
        ],
    }


def test_an_unknown_strategy_is_a_404(api) -> None:
    response = api.get("/api/signals", params={"strategy": "no_such_thing"})

    assert response.status_code == 404 and "no_such_thing" in response.json()["detail"]


def test_instruments_are_searched_by_code_or_name(api) -> None:
    assert api.get("/api/instruments", params={"q": "トヨタ"}).json() == [
        {"code": "13010", "name": "トヨタ自動車", "name_en": "Company 13010", "market": "0111"},
    ]
    assert [i["code"] for i in api.get("/api/instruments", params={"q": "130"}).json()] == ["13010", "13020"]


def test_bars_come_with_the_strategys_lines_and_its_entries(api) -> None:
    body = api.get("/api/instruments/13010/bars",
                   params={"strategy": "stand_in", "from": SESSIONS[-2].isoformat(), "to": DAY.isoformat()}).json()

    assert body["bars"] == [
        {"date": SESSIONS[-2].isoformat(), "open": 122.0, "high": 122.0, "low": 122.0, "close": 122.0, "volume": 1000.0},
        {"date": DAY.isoformat(), "open": 123.0, "high": 123.0, "low": 123.0, "close": 123.0, "volume": 1000.0},
    ]
    assert body["plots"] == [{"indicator": "close", "pane": "price"}, {"indicator": "double", "pane": "separate"}]
    assert body["lines"] == {
        "close": [{"date": SESSIONS[-2].isoformat(), "value": 122.0}, {"date": DAY.isoformat(), "value": 123.0}],
        "double": [{"date": SESSIONS[-2].isoformat(), "value": 244.0}, {"date": DAY.isoformat(), "value": 246.0}],
    }
    assert body["entries"] == [SESSIONS[-2].isoformat(), DAY.isoformat()]
