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
from app.market_data import CLOSE
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
