"""Isolated research uses the paper execution rules but never its ledger."""
from uuid import uuid4
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select, update

from app.accounts import Accounts, AccountSpec, Costs
from app.accounts import tables
from app.accounts import research_tables
from app.accounts.research import ResearchRuns
from app.config import Settings
from app.jobs import Jobs, Job, JobOutcome, JobsBusy
from app.main import create_app
from app.market_data import tables as market_tables
from app.strategies import Disposition
from tests.account_market import SESSIONS, Script, synced, fake_client


PLAN = {SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[4]: {"13010": Disposition.EXIT},
        SESSIONS[5]: {"13020": Disposition.HOLD}}
PRICES = {"13010": ["1000"] * 3 + ["1100", "1200"] + ["1150"] * 5, "13020": ["500"] * 10}


def payload(source, end=SESSIONS[5], start=SESSIONS[1], **params):
    return {"source_account_id": source, "start_date": start.isoformat(), "end_date": end.isoformat(),
            "entry_above": 0.5, "exit_below": -0.1, **params}


@pytest.fixture
def setup(migrated_database, tmp_path):
    market = synced(migrated_database, PRICES)
    build = lambda name, params: Script(PLAN if params.get("entry_above", .5) < .6 else {})
    accounts = Accounts(migrated_database, market, build_strategy=build)
    source = accounts.create(AccountSpec("来源", "technical_rating_v1", SESSIONS[1]))
    jobs = Jobs(tmp_path)
    research = ResearchRuns(migrated_database, market, jobs, strategies=build)
    jobs.start()
    yield research, jobs, accounts, source, market
    jobs.stop()


def run(research, jobs, request):
    key = str(uuid4())
    run_id = research.submit(request, key)
    assert jobs.wait_until_idle()
    result = research.get(run_id)
    assert result["status"] == "completed", result["error"]
    return run_id, result


def test_research_matches_paper_and_does_not_change_source(setup, migrated_database):
    research, jobs, accounts, source, market = setup
    accounts.advance(source, through=SESSIONS[5])
    baseline = accounts.report(source)
    with migrated_database.connect() as con:
        before = list(con.execute(select(tables.paper_orders)))
    run_id, result = run(research, jobs, payload(source))
    r = result["result"]
    assert [p["nav"] for p in r["nav"]] == [float(v) for v in baseline.nav]
    assert r["total_return"] == pytest.approx(baseline.figures.total_return)
    assert r["realised_pnl"] == pytest.approx(133065)
    assert r["unrealised_pnl"] == 0
    stored = research.orders(run_id, page_size=200)["orders"]
    assert [(o["code"], o["status"], o["execution_date"]) for o in reversed(stored)] == [
        (o.code, o.status, o.execution_date.isoformat()) for o in baseline.orders]
    with migrated_database.connect() as con:
        assert list(con.execute(select(tables.paper_orders))) == before
    _, changed = run(research, jobs, payload(source, entry_above=.6))
    assert changed["result"]["trades"] == 0
    assert changed["input_fingerprint"] == result["input_fingerprint"]


def test_single_day_and_end_holdings_pending_are_not_liquidated(setup):
    research, jobs, accounts, source, _ = setup
    _, one = run(research, jobs, payload(source, end=SESSIONS[1]))
    assert one["result"]["trades"] == 0
    assert one["result"]["total_return"] == 0
    assert one["result"]["pending"][0]["execution_date"] == SESSIONS[2].isoformat()
    _, held = run(research, jobs, payload(source, end=SESSIONS[4]))
    assert held["result"]["trades"] == 1
    assert held["result"]["unrealised_pnl"] == pytest.approx(179100)
    assert held["result"]["realised_pnl"] == 0
    assert held["result"]["pending"][0]["kind"] == "sell"
    assert held["result"]["holdings"][0]["quantity"] == 900


def test_fees_return_and_end_valuation_worked_out_by_hand(migrated_database, tmp_path):
    """A 0.1% commission (at least ¥100) and 0.1% slippage each side; 13010
    is bought on S2 and told to go on S4 (see PLAN and PRICES)."""
    market = synced(migrated_database, PRICES)
    build = lambda name, params: Script(PLAN)
    accounts = Accounts(migrated_database, market, build_strategy=build)
    costs = Costs(commission_rate=Decimal("0.001"), commission_min=Decimal("100"), slippage=Decimal("0.001"))
    source = accounts.create(AccountSpec("有手续费", "technical_rating_v1", SESSIONS[1], costs=costs))
    jobs = Jobs(tmp_path)
    research = ResearchRuns(migrated_database, market, jobs, strategies=build)
    jobs.start()
    try:
        # S1 close: NAV ¥10,000,000, a tenth less the 5% floor over 10 names = ¥950,000 → 900 shares at ¥1,000.
        # S2 open ¥1,000 +0.1% = ¥1,001: ¥900,900 plus a ¥900.90 fee; cash ¥9,098,199.10.
        # S4 close ¥1,200: 900 × 1,200 = ¥1,080,000 held, not sold (the exit is pending for S5).
        _, held = run(research, jobs, payload(source, end=SESSIONS[4]))
        r = held["result"]
        assert r["fees"] == pytest.approx(900.9)
        assert r["cash"] == pytest.approx(9_098_199.1)
        assert r["unrealised_pnl"] == pytest.approx(1_080_000 - 901_800.9)
        assert r["realised_pnl"] == pytest.approx(0)
        assert r["total_return"] == pytest.approx(10_178_199.1 / 10_000_000 - 1)
        assert r["topix_return"] == 0 and r["excess_return"] == pytest.approx(r["total_return"])
        assert r["max_drawdown"] == pytest.approx(1 - 9_998_199.1 / 10_000_000)  # S2 close, after the fee
        assert r["holdings"] == [{"code": "13010", "quantity": 900, "opened_on": SESSIONS[2].isoformat(),
                                  "cost": pytest.approx(901_800.9), "close": 1200.0, "value": 1_080_000.0}]
        assert [(p["kind"], p["code"], p["execution_date"]) for p in r["pending"]] == [
            ("sell", "13010", SESSIONS[5].isoformat())]
        # One session more: sold at the S5 open ¥1,150 −0.1% = ¥1,148.85, ¥1,033,965 less a ¥1,033.965 fee.
        _, sold = run(research, jobs, payload(source, end=SESSIONS[5]))
        r = sold["result"]
        assert r["fees"] == pytest.approx(900.9 + 1033.965)
        assert r["cash"] == pytest.approx(9_098_199.1 + 1_033_965 - 1033.965)
        assert r["realised_pnl"] == pytest.approx(1_032_931.035 - 901_800.9)
        assert r["unrealised_pnl"] == 0 and r["trades"] == 2
        assert r["total_return"] == pytest.approx(r["cash"] / 10_000_000 - 1)
    finally:
        jobs.stop()


def test_no_trade_before_the_first_session_close(setup, migrated_database, tmp_path):
    """A signal on a warm-up day never trades, and the first day's signal
    can only fill at the next session's open."""
    _, jobs, _, source, market = setup
    script = Script({SESSIONS[0]: {"13020": Disposition.HOLD}, SESSIONS[1]: {"13010": Disposition.HOLD}})
    research = ResearchRuns(migrated_database, market, jobs, strategies=lambda name, params: script)
    run_id, result = run(research, jobs, payload(source, start=SESSIONS[1], end=SESSIONS[3]))
    assert [day for day, _ in script.asked] == SESSIONS[1:4]  # warm-up days are never asked
    orders = list(reversed(research.orders(run_id, page_size=200)["orders"]))
    assert all(o["signal_date"] >= SESSIONS[1].isoformat() for o in orders)
    assert not [o for o in orders if o["execution_date"] == SESSIONS[1].isoformat()]
    filled = [o for o in orders if o["status"] == "filled"]
    assert [(o["code"], o["signal_date"], o["execution_date"], o["fill_price"]) for o in filled] == [
        ("13010", SESSIONS[1].isoformat(), SESSIONS[2].isoformat(), pytest.approx(1001))]
    assert result["result"]["nav"][0] == {"date": SESSIONS[1].isoformat(), "nav": 10_000_000, "nav_curve": 1,
                                          "topix_curve": 1, "drawdown": 0}


def later_sync(engine, after):
    """What a routine sync does to data after `after`: the calendar reloaded one
    day longer, later bars restated, one listing ending and another starting."""
    calendar, periods, bars = market_tables.trading_calendar, market_tables.segment_periods, market_tables.daily_bars
    with engine.begin() as con:
        days = [dict(row) for row in con.execute(select(calendar)).mappings()]
        con.execute(delete(calendar))
        con.execute(insert(calendar), days + [{"date": max(d["date"] for d in days) + timedelta(days=1),
                                               "holiday_division": 1}])
        con.execute(update(bars).where(bars.c.code == "13010", bars.c.date > after).values(close=Decimal("1300")))
        con.execute(update(periods).where(periods.c.code == "13020", periods.c.valid_to.is_(None))
                    .values(valid_to=after))
        con.execute(insert(periods).values(code="13030", valid_from=after + timedelta(days=1), valid_to=None,
                                           market_code="0111", product_category="011", sector33="3700"))


def test_input_fingerprint_ignores_later_syncs_but_not_changes_in_range(setup, migrated_database):
    research, jobs, accounts, source, market = setup
    _, old = run(research, jobs, payload(source))
    later_sync(migrated_database, SESSIONS[7])
    _, again = run(research, jobs, payload(source))
    assert again["input_fingerprint"] == old["input_fingerprint"]
    assert again["result"] == old["result"]
    # The roster changing inside the range is a different input.
    periods = market_tables.segment_periods
    with migrated_database.begin() as con:
        con.execute(update(periods).where(periods.c.code == "13020").values(valid_to=SESSIONS[3]))
    assert market.input_fingerprint(SESSIONS[0], SESSIONS[5])["sha256"] != old["input_fingerprint"]["sha256"]


def test_saved_results_survive_source_deletion_and_market_correction(setup, migrated_database):
    research, jobs, accounts, source, market = setup
    run_id, old = run(research, jobs, payload(source))
    with migrated_database.begin() as con:
        con.execute(update(market_tables.daily_bars).where(market_tables.daily_bars.c.code == "13010",
                    market_tables.daily_bars.c.date == SESSIONS[3]).values(close=Decimal("1111")))
    _, new = run(research, jobs, payload(source))
    assert new["input_fingerprint"]["sha256"] != old["input_fingerprint"]["sha256"]
    assert new["input_fingerprint"]["rows"] == old["input_fingerprint"]["rows"]
    accounts.delete(source)
    assert research.get(run_id) == old


@pytest.mark.parametrize("changes,match", [
    ({"start_date": "2026-08-31"}, "开市日"),
    ({"start_date": SESSIONS[6].isoformat()}, "晚于"),
    ({"start_date": SESSIONS[0].isoformat()}, "预热期"),
    ({"end_date": (SESSIONS[-1] + timedelta(days=1)).isoformat()}, "缺失"),
    ({"entry_above": float("inf")}, "有限数值"),
    ({"exit_below": -1.01}, "有限数值"),
])
def test_validation_leaves_no_run(setup, changes, match):
    research, jobs, _, source, _ = setup
    with pytest.raises(ValueError, match=match):
        research.submit(payload(source, **changes), str(uuid4()))
    assert research.history()["total"] == 0
    assert jobs.current() is None


def test_idempotency_busy_restart_and_retry(setup, migrated_database, tmp_path):
    research, jobs, accounts, source, market = setup
    request, key = payload(source), str(uuid4())
    run_id = research.submit(request, key)
    assert research.submit(request, key) == run_id
    assert jobs.wait_until_idle()
    assert research.submit(request, key) == run_id
    with pytest.raises(ValueError, match="请求标识"):
        research.submit(payload(source, entry_above=.7), key)
    # Simulate a run left in progress by a crashed service.
    with migrated_database.begin() as con:
        con.execute(update(research_tables.runs).where(research_tables.runs.c.id == run_id)
                    .values(status="running", result=None))
    research.recover()
    assert research.get(run_id)["status"] == "failed"
    accounts.delete(source)
    retry = research.submit({}, str(uuid4()), retry_of=run_id)
    assert jobs.wait_until_idle()
    assert research.get(retry)["status"] == "completed"
    assert research.get(retry)["retry_of"] == run_id
    assert research.get(run_id)["status"] == "failed"


def rival_first(monkeypatch, jobs, rival, *, finished):
    """The same request sent twice at once: `rival` gets the writer lock
    between this call's request-key lookup and its own submit, and is still
    running then unless `finished`."""
    real = jobs.submit

    def submit(job, *, prepare=None):
        monkeypatch.setattr(jobs, "submit", real)
        rival()
        if finished:
            assert jobs.wait_until_idle()
        return real(job, prepare=prepare)
    monkeypatch.setattr(jobs, "submit", submit)


@pytest.mark.parametrize("finished", [True, False], ids=["rival-finished", "rival-running"])
def test_same_request_sent_twice_at_once_is_one_run(setup, monkeypatch, finished):
    research, jobs, _, source, _ = setup
    request, key, first = payload(source), str(uuid4()), []
    rival_first(monkeypatch, jobs, lambda: first.append(research.submit(request, key)), finished=finished)
    assert research.submit(request, key) == first[0]
    assert jobs.wait_until_idle()
    assert research.history()["total"] == 1


def test_shared_writer_lock_and_live_run_not_recovered(setup, tmp_path):
    from threading import Event
    research, jobs, _, source, _ = setup
    release = Event()
    jobs.submit(Job("sync", lambda _: (release.wait(3), JobOutcome())[1]))
    try:
        with pytest.raises(JobsBusy):
            research.submit(payload(source), str(uuid4()))
        research.recover()
        assert research.history()["total"] == 0
    finally:
        release.set()
        assert jobs.wait_until_idle()


def test_http_submit_poll_page_and_invalid_input(migrated_database):
    app = create_app(Settings(_env_file=None), client=fake_client(PRICES), today=lambda: SESSIONS[-1],
                     strategies=lambda name, params: Script(PLAN))
    with TestClient(app) as client:
        app.state.market.sync()
        source = app.state.accounts.create(AccountSpec("来源", "technical_rating_v1", SESSIONS[1]))
        assert client.get("/api/research/sources").json()[0]["id"] == source
        body = {**payload(source), "request_key": str(uuid4())}
        response = client.post("/api/research/runs", json=body)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert app.state.jobs.wait_until_idle()
        assert client.post("/api/research/runs", json=body).json()["id"] == run_id
        detail = client.get(f"/api/research/runs/{run_id}").json()
        assert detail["status"] == "completed", detail
        assert "request_key" not in detail
        page = client.get(f"/api/research/runs/{run_id}/orders?page_size=1").json()
        assert page["total"] == 3 and len(page["orders"]) == 1
        assert client.get("/api/research/runs").json()["total"] == 1
        assert client.get("/api/research/runs/missing").status_code == 404
        assert client.post("/api/research/runs", json={**body, "entry_above": 2}).status_code == 422
        assert client.post(f"/api/research/runs/{run_id}/retry", json={"request_key": str(uuid4())}).status_code == 422


def test_legacy_0004_tables_are_preserved_on_upgrade(tmp_path, monkeypatch):
    import sqlite3
    from alembic.script import ScriptDirectory
    from app.migrate import _config, upgrade_to_head
    head = ScriptDirectory.from_config(_config()).get_current_head()
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        con.execute("INSERT INTO alembic_version VALUES ('0004')")
        con.execute("CREATE TABLE research_runs (id INTEGER PRIMARY KEY, result TEXT)")
        con.execute("INSERT INTO research_runs VALUES (1, 'legacy-result')")
    monkeypatch.setenv("DATABASE_PATH", str(path))
    upgrade_to_head()
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT * FROM research_runs").fetchall() == [(1, "legacy-result")]
        assert con.execute("SELECT COUNT(*) FROM manual_research_runs").fetchone() == (0,)
        assert con.execute("SELECT * FROM alembic_version").fetchone() == (head,)
