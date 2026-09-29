"""Interval discovery over HTTP: TOPIX regimes find the ranges, the user
picks some, and one configuration runs over each as a research batch."""
from datetime import date, timedelta
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.accounts import AccountSpec, regimes
from app.accounts import research_tables
from app.accounts.research_batches import MAX_BATCH_RUNS
from app.config import Settings
from app.jobs import Job, JobOutcome
from app.main import create_app
from app.market_data import tables as market_tables
from app.market_data.jquants import IndexBar
from app.strategies import Disposition
from tests.account_market import LIQUID, Script
from tests.fakes import FakeJQuants, bar, listed


def weekdays(start: date, count: int) -> list[date]:
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


S = weekdays(date(2025, 1, 6), 330)


def topix_closes() -> list[Decimal]:
    """A steady rise (one long up-trend from the 220th close), a sharp fall,
    a quick recovery (a second one), then every other day dipping 20% — a
    run of single-day up-trends, 21 intervals in all."""
    closes, base = [], 1000.0
    for i in range(len(S)):
        base *= 1.002 if i < 250 else 0.985 if i < 265 else 1.01 if i < 290 else 1.002
        closes.append(Decimal(str(round(base * (0.8 if i >= 290 and i % 2 else 1.0), 2))))
    return closes


CLOSES = dict(zip(S, topix_closes()))
CANDIDATES = 21
PLAN = {day: {"13010": Disposition.HOLD} for day in S}


class Flaky(Script):
    def __init__(self, plan, boom):
        super().__init__(plan)
        self.boom = boom

    def evaluate(self, frame, day, holdings):
        if day in self.boom:
            raise RuntimeError(f"策略在 {day} 出错")
        return super().evaluate(frame, day, holdings)


def fake_market() -> FakeJQuants:
    bars = {day: [bar("13010", day, str(1000 + n), turnover=LIQUID), bar("13020", day, "500", turnover=LIQUID)]
            for n, day in enumerate(S)}
    topix = [IndexBar(day, close, close, close, close) for day, close in CLOSES.items()]
    ahead = weekdays(S[-1] + timedelta(days=1), 3)  # the calendar runs ahead of the data
    return FakeJQuants(S + ahead, bars=bars, roster=[listed("13010"), listed("13020")], topix=topix)


def make_app(boom: set) -> object:
    return create_app(Settings(_env_file=None), client=fake_market(), today=lambda: S[-1],
                      strategies=lambda name, params: Flaky(PLAN, boom))


@pytest.fixture
def env(migrated_database):
    boom: set[date] = set()
    app = make_app(boom)
    with TestClient(app) as http:
        yield SimpleNamespace(app=app, http=http, engine=migrated_database, boom=boom,
                              jobs=app.state.jobs, source=None)


def ready(env, until=None):
    env.app.state.market.sync(until=until)
    env.source = env.app.state.accounts.create(AccountSpec("来源", "technical_rating_v1", S[1]))


def post_discovery(env, key=None, **body):
    body = {"request_key": key or str(uuid4()), "search_from": S[0].isoformat(),
            "search_to": S[-1].isoformat(), "trend": "up", "volatility": None, **body}
    return env.http.post("/api/research/discoveries", json=body)


def discover(env, **body) -> dict:
    response = post_discovery(env, **body)
    assert response.status_code == 202, response.text
    assert env.jobs.wait_until_idle()
    return env.http.get(f"/api/research/discoveries/{response.json()['id']}").json()


def post_batch(env, discovery_id, ids, key=None, **body):
    body = {"request_key": key or str(uuid4()), "discovery_id": discovery_id, "interval_ids": ids,
            "source_account_id": env.source, "entry_above": .5, "exit_below": -.1, **body}
    return env.http.post("/api/research/batches", json=body)


def run_batch(env, discovery_id, ids) -> dict:
    response = post_batch(env, discovery_id, ids)
    assert response.status_code == 202, response.text
    assert env.jobs.wait_until_idle()
    return env.http.get(f"/api/research/batches/{response.json()['id']}").json()


def counts(engine):
    with engine.connect() as con:
        return [con.execute(select(func.count()).select_from(t)).scalar_one()
                for t in (research_tables.batches, research_tables.runs)]


def set_topix(engine, day, close):
    bars = market_tables.daily_bars
    with engine.begin() as con:
        con.execute(update(bars).where(bars.c.code == "TOPIX", bars.c.date == day).values(close=close))


def test_discovery_lists_every_interval_and_a_batch_runs_the_chosen_ones(env):
    ready(env)
    definition = env.http.get("/api/research/regimes/definition").json()
    assert definition["version"] == "topix_trend_vol_v1"
    assert (definition["topix_from"], definition["topix_through"]) == (S[0].isoformat(), S[-1].isoformat())
    assert definition["ma_sessions"] == 200 and "MA200" in definition["formulas"]["ma200"]

    found = discover(env)
    assert found["status"] == "completed", found["error"]
    assert found["parameters"] == {"search_from": S[0].isoformat(), "search_to": S[-1].isoformat(),
                                   "trend": "up", "volatility": None}
    assert found["definition_version"] == "topix_trend_vol_v1" and found["max_batch_runs"] == MAX_BATCH_RUNS
    # What the service stored is exactly what the classifier finds on the same closes.
    expected = regimes.discover(S, CLOSES, S[0], S[-1], regimes.RegimeFilter("up"))
    assert len(found["intervals"]) == len(expected.intervals) == CANDIDATES
    assert [i["id"] for i in found["intervals"]] == list(range(1, CANDIDATES + 1))
    for got, want in zip(found["intervals"], expected.intervals):
        assert (got["start_date"], got["end_date"], got["sessions"], got["single_day"], got["short"],
                got["truncated_start"], got["at_search_end"]) == (
            want.start.isoformat(), want.end.isoformat(), want.sessions, want.single_day, want.short,
            want.truncated_start, want.at_search_end)
        assert got["topix_return"] == pytest.approx(want.topix_return)
        assert got["sessions_before"] == S.index(want.start)
    first = found["intervals"][0]
    assert (first["start_date"], first["sessions"], first["sessions_before"]) == (S[219].isoformat(), 42, 219)
    assert found["intervals"][2]["single_day"]
    assert found["fingerprint"] == regimes.fingerprint(S, CLOSES)
    assert found["diagnostics"]["warmup_unknown"] == [[S[0].isoformat(), S[218].isoformat()]]
    assert found["diagnostics"]["gaps"] == [] and found["batches"] == []

    batch = run_batch(env, found["id"], [2, 1])
    assert batch["status"] == "completed"
    assert batch["discovery_id"] == found["id"]
    assert batch["selection"] == {"interval_ids": [1, 2], "candidate_count": CANDIDATES}
    assert batch["input_check"] == found["fingerprint"]
    assert [(s["position"], s["interval_id"], s["start_date"], s["end_date"]) for s in batch["segments"]] == [
        (n, i["id"], i["start_date"], i["end_date"]) for n, i in enumerate(found["intervals"][:2], 1)]
    assert batch["distribution"]["denominator"] == 2
    returns = [s["metrics"]["total_return"] for s in batch["segments"]]
    assert returns[0] != returns[1]
    # A segment opens in the manual run view like any other run, but is not listed there.
    run = env.http.get(f"/api/research/runs/{batch['segments'][0]['run_id']}").json()
    assert run["status"] == "completed" and run["config"]["start_date"] == first["start_date"]
    assert env.http.get("/api/research/runs").json()["total"] == 0

    again = env.http.get(f"/api/research/discoveries/{found['id']}").json()
    assert again["batches"] == [{"id": batch["id"], "created_at": batch["created_at"],
                                 "selection": batch["selection"], "status": "completed"}]
    listed = env.http.get("/api/research/batches").json()
    assert listed["total"] == 1
    assert listed["batches"][0]["id"] == batch["id"] and listed["batches"][0]["discovery_id"] == found["id"]
    assert (listed["batches"][0]["segments"], listed["batches"][0]["completed"]) == (2, 2)
    # Reading never starts anything; a lost response resent with its key is the same batch.
    jobs = len(env.jobs.history())
    for path in (f"/api/research/discoveries/{found['id']}", f"/api/research/batches/{batch['id']}",
                 "/api/research/batches", "/api/research/regimes/definition"):
        assert env.http.get(path).status_code == 200
    assert len(env.jobs.history()) == jobs and env.jobs.current() is None
    key = str(uuid4())
    first_id = post_batch(env, found["id"], [3], key=key).json()["id"]
    assert env.jobs.wait_until_idle()
    assert post_batch(env, found["id"], [3], key=key).json()["id"] == first_id
    assert post_batch(env, found["id"], [4], key=key).status_code == 422


def test_zero_match_is_a_completed_discovery_with_no_intervals(env):
    ready(env)
    found = discover(env, search_to=S[200].isoformat())
    assert found["status"] == "completed"
    assert found["intervals"] == []
    assert found["diagnostics"]["matched_sessions"] == 0
    assert found["diagnostics"]["warmup_unknown"] == [[S[0].isoformat(), S[200].isoformat()]]
    down = discover(env, trend="down", volatility="high")
    assert down["status"] == "completed" and down["intervals"] == []
    # A later search reads back only as far as its first labels need.
    later = discover(env, search_from=S[300].isoformat(), trend="up", volatility="high")
    assert later["fingerprint"]["from"] == S[300 - 273].isoformat()
    expected = regimes.discover(S, CLOSES, S[300], S[-1], regimes.RegimeFilter("up", "high"))
    assert [(i["start_date"], i["truncated_start"]) for i in later["intervals"]] == [
        (i.start.isoformat(), i.truncated_start) for i in expected.intervals]


def test_rejected_requests_write_nothing(env):
    ready(env)
    assert post_discovery(env, search_to=(S[-1] + timedelta(days=1)).isoformat()).status_code == 422
    assert "超出" in post_discovery(env, search_to=(S[-1] + timedelta(days=7)).isoformat()).json()["detail"]
    assert post_discovery(env, search_from=S[5].isoformat(), search_to=S[4].isoformat()).status_code == 422
    assert post_discovery(env, trend="sideways").status_code == 422
    key = str(uuid4())
    assert post_discovery(env, key=key).status_code == 202
    assert env.jobs.wait_until_idle()
    assert post_discovery(env, key=key).status_code == 202
    assert post_discovery(env, key=key, trend="down").status_code == 422
    found = env.http.get(f"/api/research/discoveries/{post_discovery(env, key=key).json()['id']}").json()
    assert env.http.get("/api/research/discoveries/missing").status_code == 404

    empty = counts(env.engine)
    foreign = post_batch(env, found["id"], [1, 99, 100])
    assert foreign.status_code == 422 and "99" in foreign.json()["detail"] and "100" in foreign.json()["detail"]
    assert post_batch(env, found["id"], []).status_code == 422
    over = post_batch(env, found["id"], list(range(1, CANDIDATES + 1)))
    assert over.status_code == 422
    assert f"所选 {CANDIDATES} 段超过单批上限 {MAX_BATCH_RUNS}" in over.json()["detail"]
    assert post_batch(env, "missing", [1]).status_code == 404
    assert post_batch(env, found["id"], [1], entry_above=2).status_code == 422
    assert env.http.get("/api/research/batches/missing").status_code == 404
    with env.engine.begin() as con:
        con.execute(update(research_tables.discoveries).where(research_tables.discoveries.c.id == found["id"])
                    .values(status="failed"))
    assert "尚未完成" in post_batch(env, found["id"], [1]).json()["detail"]
    assert counts(env.engine) == empty


def test_topix_changed_since_discovery_is_refused_but_later_days_are_not(env):
    ready(env, until=S[299])
    assert env.http.get("/api/research/regimes/definition").json()["topix_through"] == S[299].isoformat()
    assert post_discovery(env, search_to=S[300].isoformat()).status_code == 422
    found = discover(env, search_to=S[299].isoformat())
    assert len(found["intervals"]) >= 2

    # The daily sync appends days after the search end: the discovery still holds.
    env.app.state.market.sync()
    assert env.http.get("/api/research/regimes/definition").json()["topix_through"] == S[-1].isoformat()
    batch = run_batch(env, found["id"], [1, 2])
    assert batch["status"] == "completed"

    # A close the discovery read is corrected: its intervals may no longer hold.
    empty = counts(env.engine)
    set_topix(env.engine, S[250], Decimal("1234.5"))
    stale = post_batch(env, found["id"], [1, 2])
    assert stale.status_code == 412 and "重新发现" in stale.json()["detail"]
    assert counts(env.engine) == empty
    assert env.jobs.current() is None


def test_failed_segment_retried_alone_unless_topix_changed_or_busy(env):
    ready(env)
    found = discover(env)
    env.boom.add(S[230])  # inside the first interval
    batch = run_batch(env, found["id"], [1, 2])
    assert batch["status"] == "partial"
    assert [s["status"] for s in batch["segments"]] == ["failed", "completed"]
    assert batch["distribution"]["denominator"] == 1 and batch["distribution"]["failed"] == 1
    env.boom.clear()
    retry = f"/api/research/batches/{batch['id']}/segments/1/retry"
    assert env.http.post(f"/api/research/batches/{batch['id']}/segments/2/retry",
                         json={"request_key": str(uuid4())}).status_code == 422
    assert env.http.post(f"/api/research/batches/{batch['id']}/segments/9/retry",
                         json={"request_key": str(uuid4())}).status_code == 404

    original = CLOSES[S[240]]
    set_topix(env.engine, S[240], Decimal("1"))
    assert env.http.post(retry, json={"request_key": str(uuid4())}).status_code == 412
    set_topix(env.engine, S[240], original)

    release = Event()
    env.jobs.submit(Job("sync", lambda _: (release.wait(3), JobOutcome())[1]))
    try:
        assert env.http.post(retry, json={"request_key": str(uuid4())}).status_code == 409
        assert post_discovery(env).status_code == 409
        assert post_batch(env, found["id"], [3]).status_code == 409
    finally:
        release.set()
        assert env.jobs.wait_until_idle()

    key = str(uuid4())
    accepted = env.http.post(retry, json={"request_key": key})
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["id"] == batch["id"]
    assert env.jobs.wait_until_idle()
    assert env.http.post(retry, json={"request_key": key}).json() == accepted.json()
    batch = env.http.get(f"/api/research/batches/{batch['id']}").json()
    assert batch["status"] == "completed"
    assert batch["segments"][0]["run_id"] == accepted.json()["run_id"]
    assert [a["status"] for a in batch["segments"][0]["attempts"]] == ["failed", "completed"]


def test_discoveries_survive_a_restart_and_unfinished_ones_are_failed(migrated_database):
    boom: set[date] = set()
    first = make_app(boom)
    with TestClient(first) as http:
        env = SimpleNamespace(app=first, http=http, engine=migrated_database, jobs=first.state.jobs, source=None)
        ready(env)
        found = discover(env)
        cut_off = post_discovery(env).json()["id"]
        assert env.jobs.wait_until_idle()
    table = research_tables.discoveries
    with migrated_database.begin() as con:  # as if the service died while it ran
        con.execute(update(table).where(table.c.id == cut_off).values(status="running"))

    with TestClient(make_app(boom)) as http:
        assert http.get(f"/api/research/discoveries/{found['id']}").json() == found
        interrupted = http.get(f"/api/research/discoveries/{cut_off}").json()
        assert interrupted["status"] == "failed" and "服务中断" in interrupted["error"]
