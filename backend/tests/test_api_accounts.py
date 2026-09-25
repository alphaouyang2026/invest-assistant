"""The account pages' API: `/api/accounts…` and `/api/strategies`.

Handlers only translate (spec A.6), so these check the shapes and the
wiring — that creating an account queues its advance, that the figures and
lists come through — not the rules behind them, which are tested on
`Accounts` and its parts.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.strategies import Disposition
from tests.account_market import SESSIONS, Script, fake_client

PLAN = {SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[-1]: {"13020": Disposition.HOLD}}


@pytest.fixture
def api(migrated_database):
    client = fake_client({"13010": ["1000"] * 5 + ["1100"] * 5, "13020": ["500"] * 10})
    app = create_app(Settings(_env_file=None), client=client, today=lambda: SESSIONS[-1],
                     strategies=lambda name, params: Script(PLAN))
    with TestClient(app) as test_client:
        app.state.market.sync()
        yield test_client


def wait_for_idle(api: TestClient) -> None:
    deadline = time.monotonic() + 10
    while api.get("/api/jobs/current").json() is not None:
        assert time.monotonic() < deadline, "the job never finished"
        time.sleep(0.02)


NEW = {"name": "试", "strategy": "script", "start_date": SESSIONS[1].isoformat()}


def test_creating_an_account_backtests_it_and_its_pages_can_be_read(api) -> None:
    created = api.post("/api/accounts", json=NEW)
    assert created.status_code == 201 and created.json()["advance_job_id"]
    account = created.json()["id"]
    wait_for_idle(api)

    [listed] = api.get("/api/accounts").json()
    assert (listed["id"], listed["name"], listed["advanced_through"], listed["status"]) == (
        account, "试", SESSIONS[-1].isoformat(), "active")

    detail = api.get(f"/api/accounts/{account}").json()
    assert detail["rules"]["max_positions"] == 10 and detail["figures"]["total_return"] == pytest.approx(
        listed["total_return"])
    assert [(h["code"], h["quantity"]) for h in detail["holdings"]] == [("13010", 900)]
    tomorrow = (SESSIONS[-1] + timedelta(days=1)).isoformat()
    assert [(o["kind"], o["code"], o["execution_date"]) for o in detail["pending"]] == [("buy", "13020", tomorrow)]

    nav = api.get(f"/api/accounts/{account}/nav").json()
    assert [point["date"] for point in nav] == [day.isoformat() for day in SESSIONS[1:]]
    assert nav[0]["nav_curve"] == 1.0 and nav[0]["topix_curve"] == 1.0 and "drawdown" in nav[0]

    orders = api.get(f"/api/accounts/{account}/orders").json()
    assert [(o["kind"], o["code"], o["status"]) for o in orders][:1] == [("buy", "13010", "filled")]


def test_an_account_that_cannot_be_created_is_a_422_with_the_reason(api) -> None:
    before_data = {**NEW, "start_date": (SESSIONS[0] - timedelta(days=1)).isoformat()}

    refused = api.post("/api/accounts", json=before_data)

    assert refused.status_code == 422 and "开市日" in refused.json()["detail"]
    assert api.get("/api/accounts").json() == []


def test_stopping_and_deleting_and_a_missing_account_is_a_404(api) -> None:
    account = api.post("/api/accounts", json=NEW).json()["id"]
    wait_for_idle(api)

    assert api.post(f"/api/accounts/{account}/stop").status_code == 204
    assert api.get(f"/api/accounts/{account}").json()["status"] == "stopped"
    assert api.delete(f"/api/accounts/{account}").status_code == 204
    assert api.get(f"/api/accounts/{account}").status_code == 404
    assert api.post(f"/api/accounts/{account}/stop").status_code == 404


def test_the_strategies_and_their_defaults_for_the_new_account_page(api) -> None:
    listed = {s["name"]: s["defaults"] for s in api.get("/api/strategies").json()}

    assert set(listed) == {"trend_pullback_v1", "technical_rating_v1"}
    assert listed["technical_rating_v1"]["entry_above"] == 0.5
