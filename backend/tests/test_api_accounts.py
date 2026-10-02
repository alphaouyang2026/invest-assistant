"""The account pages' API: `/api/accounts…` and `/api/strategies`.

Handlers only translate (spec A.6), so these check the shapes and the
wiring — that creating an account queues its advance, that the figures and
lists come through — not the rules behind them, which are tested on
`Accounts` and its parts.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.strategies import Disposition
from tests.account_market import SESSIONS, Script, fake_client

PLAN = {SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[-1]: {"13020": Disposition.HOLD}}


@contextmanager
def serving(plan):
    client = fake_client({"13010": ["1000"] * 5 + ["1100"] * 5, "13020": ["500"] * 10})
    app = create_app(Settings(_env_file=None), client=client, today=lambda: SESSIONS[-1],
                     strategies=lambda name, params: Script(plan))
    with TestClient(app) as test_client:
        app.state.market.sync()
        yield test_client


@pytest.fixture
def api(migrated_database):
    with serving(PLAN) as test_client:
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
    assert [(h["code"], h["name"], h["quantity"]) for h in detail["holdings"]] == [("13010", "会社13010", 900)]
    tomorrow = (SESSIONS[-1] + timedelta(days=1)).isoformat()
    assert [(o["kind"], o["code"], o["name"], o["execution_date"]) for o in detail["pending"]] == [
        ("buy", "13020", "会社13020", tomorrow)]

    nav = api.get(f"/api/accounts/{account}/nav").json()
    assert [point["date"] for point in nav] == [day.isoformat() for day in SESSIONS[1:]]
    assert nav[0]["nav_curve"] == 1.0 and nav[0]["topix_curve"] == 1.0 and "drawdown" in nav[0]

    history = api.get(f"/api/accounts/{account}/orders").json()
    assert [(o["kind"], o["code"], o["name"], o["status"]) for o in history["orders"]] == [
        ("buy", "13010", "会社13010", "filled")]  # tomorrow's order is not history yet


def test_the_order_history_comes_newest_first_a_page_at_a_time_and_by_kind(migrated_database) -> None:
    bought_sold_bought = {SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[3]: {"13010": Disposition.EXIT},
                          SESSIONS[5]: {"13010": Disposition.HOLD}}
    with serving(bought_sold_bought) as api:
        account = api.post("/api/accounts", json=NEW).json()["id"]
        wait_for_idle(api)
        orders = f"/api/accounts/{account}/orders"

        first = api.get(orders, params={"page_size": 2}).json()
        second = api.get(orders, params={"page_size": 2, "page": 2}).json()
        sells = api.get(orders, params={"kind": "sell"}).json()

    assert (first["total"], first["page"], first["page_size"]) == (3, 1, 2)
    assert first["counts"] == {"all": 3, "buy": 2, "sell": 1, "skipped": 0, "events": 0}
    assert [(o["kind"], o["execution_date"]) for o in first["orders"] + second["orders"]] == [
        ("buy", SESSIONS[6].isoformat()), ("sell", SESSIONS[4].isoformat()), ("buy", SESSIONS[2].isoformat())]
    assert sells["total"] == 1 and [o["kind"] for o in sells["orders"]] == ["sell"]


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
    """Each with its parameters' defaults, the universe rule it buys under,
    and the portfolio rules the page fills in for it."""
    listed = {s["name"]: s for s in api.get("/api/strategies").json()}

    assert set(listed) == {"trend_pullback_v1", "technical_rating_v1", "topix_buy_and_hold_v1"}
    assert listed["technical_rating_v1"]["defaults"]["entry_above"] == 0.5
    for stock_strategy in ("trend_pullback_v1", "technical_rating_v1"):
        assert (listed[stock_strategy]["universe_rule"], listed[stock_strategy]["suggested_rules"]) == (
            "prime_common_stock", {"max_positions": 10, "max_weight": 0.1, "cash_floor": 0.05})
    assert listed["topix_buy_and_hold_v1"] == {
        "name": "topix_buy_and_hold_v1",
        "defaults": {"warmup_sessions": 1},
        "universe_rule": "topix_etf",
        "suggested_rules": {"max_positions": 1, "max_weight": 1.0, "cash_floor": 0.05},  # about 95% in 1306
    }
