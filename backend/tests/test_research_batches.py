"""A research batch runs one configuration over several ranges; each segment
is an ordinary research run, replayed exactly as a manual one."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.accounts import Accounts, AccountSpec
from app.accounts import tables
from app.accounts import research_tables
from app.accounts.research import ResearchRuns
from app.accounts.research_batches import MAX_BATCH_RUNS, ResearchBatches, SegmentSpec, StaleInput, distribution
from app.jobs import Job, JobOutcome, Jobs, JobsBusy
from app.market_data import tables as market_tables
from tests.account_market import SESSIONS, Script, synced
from tests.test_research import PLAN, PRICES, later_sync, payload, rival_first

S = SESSIONS
SEGMENTS = [SegmentSpec(S[1], S[2], 1), SegmentSpec(S[3], S[5], 2), SegmentSpec(S[6], S[8], 3)]


class Flaky(Script):
    """The scripted strategy, raising on the days in `boom`."""

    def __init__(self, plan, boom):
        super().__init__(plan)
        self.boom = boom

    def evaluate(self, frame, day, holdings):
        if day in self.boom:
            raise RuntimeError(f"策略在 {day} 出错")
        return super().evaluate(frame, day, holdings)


@pytest.fixture
def env(migrated_database, tmp_path):
    market = synced(migrated_database, PRICES)
    boom: set[date] = set()
    build = lambda name, params: Flaky(PLAN if params.get("entry_above", .5) < .6 else {}, boom)
    accounts = Accounts(migrated_database, market, build_strategy=build)
    source = accounts.create(AccountSpec("来源", "technical_rating_v1", S[1]))
    jobs = Jobs(tmp_path)
    research = ResearchRuns(migrated_database, market, jobs, strategies=build)
    batches = ResearchBatches(migrated_database, research, jobs)
    jobs.start()
    yield SimpleNamespace(engine=migrated_database, market=market, boom=boom, accounts=accounts, source=source,
                          jobs=jobs, research=research, batches=batches)
    jobs.stop()


def submit(env, segments=SEGMENTS, key=None, **options):
    batch_id = env.batches.submit(source_account_id=env.source, entry_above=.5, exit_below=-.1,
                                  segments=segments, key=key or str(uuid4()), **options)
    assert env.jobs.wait_until_idle()
    return batch_id


def rows(engine):
    with engine.connect() as con:
        return [con.execute(select(func.count()).select_from(table)).scalar_one() for table in
                (research_tables.batches, research_tables.batch_segments, research_tables.batch_attempts,
                 research_tables.runs)]


def test_each_segment_is_an_ordinary_run_with_its_own_capital(env):
    with env.engine.connect() as con:
        before = [list(con.execute(select(t))) for t in (tables.paper_accounts, tables.paper_orders)]
    batch = env.batches.get(submit(env))
    job = env.jobs.history()[0]
    assert (job.kind, job.summary) == ("research_batch", {"batch_id": batch["id"], "completed": 3, "failed": 0})
    assert batch["status"] == "completed"
    assert [s["status"] for s in batch["segments"]] == ["completed"] * 3
    assert [s["position"] for s in batch["segments"]] == [1, 2, 3]
    first, second, _ = batch["segments"]
    # The first segment ends holding 13010 (bought on S2); the second starts flat
    # with the source's capital, so the scripted exit on S4 has nothing to sell.
    assert first["metrics"]["holdings"] == 1
    child = env.research.get(second["run_id"])
    assert child["result"]["nav"][0]["nav"] == 10_000_000
    assert [p["kind"] for p in child["result"]["pending"]] == ["buy"]
    assert second["metrics"] == {
        "sessions": 3, "total_return": 0, "topix_return": 0, "excess_return": 0, "max_drawdown": 0,
        "trades": 0, "fees": 0, "realised_pnl": 0, "unrealised_pnl": 0, "holdings": 0, "pending": 1}
    # The same segment run by hand is the same run.
    manual_id = env.research.submit(payload(env.source, start=S[3], end=S[5]), str(uuid4()))
    assert env.jobs.wait_until_idle()
    manual = env.research.get(manual_id)
    for field in ("config", "result", "input_fingerprint", "status"):
        assert child[field] == manual[field], field
    assert env.research.orders(child["id"]) == env.research.orders(manual_id)
    # Its first segment too, trades and all.
    manual_id = env.research.submit(payload(env.source, start=S[1], end=S[2]), str(uuid4()))
    assert env.jobs.wait_until_idle()
    assert env.research.get(first["run_id"])["result"] == env.research.get(manual_id)["result"]
    with env.engine.connect() as con:
        assert [list(con.execute(select(t))) for t in (tables.paper_accounts, tables.paper_orders)] == before
    assert "start_date" not in batch["config"] and batch["config"]["source_account_id"] == env.source
    assert batch["max_batch_runs"] == MAX_BATCH_RUNS


def test_partial_failure_and_retry_of_one_segment(env):
    env.boom.add(S[4])
    batch_id = submit(env)
    batch = env.batches.get(batch_id)
    assert batch["status"] == "partial"
    assert [s["status"] for s in batch["segments"]] == ["completed", "failed", "completed"]
    failed = batch["segments"][1]
    assert "出错" in failed["error"] and failed["metrics"] is None
    spread = batch["distribution"]
    assert (spread["completed"], spread["failed"], spread["denominator"], len(spread["returns"])) == (2, 1, 2, 2)
    assert env.jobs.history()[0].summary == {"batch_id": batch_id, "completed": 2, "failed": 1}
    # Batch segments are listed with their batch, never among manual runs,
    # and are retried there.
    assert env.research.history()["total"] == 0
    with pytest.raises(ValueError, match="批次"):
        env.research.submit({}, str(uuid4()), retry_of=failed["run_id"])
    with pytest.raises(ValueError, match="失败"):
        env.batches.retry(batch_id, 1, str(uuid4()))
    with pytest.raises(LookupError):
        env.batches.retry(batch_id, 9, str(uuid4()))
    with pytest.raises(LookupError):
        env.batches.retry("missing", 2, str(uuid4()))

    env.boom.clear()
    key = str(uuid4())
    run_id = env.batches.retry(batch_id, 2, key)
    assert env.batches.retry(batch_id, 2, key) == run_id
    assert env.jobs.wait_until_idle()
    with pytest.raises(ValueError, match="请求标识"):
        env.batches.retry(batch_id, 3, key)
    batch = env.batches.get(batch_id)
    assert batch["status"] == "completed"
    retried = batch["segments"][1]
    assert retried["run_id"] == run_id and retried["error"] is None
    assert [(a["attempt"], a["status"]) for a in retried["attempts"]] == [(1, "failed"), (2, "completed")]
    assert retried["attempts"][1]["retry_of"] == failed["run_id"]
    assert env.research.get(failed["run_id"])["status"] == "failed"
    assert batch["distribution"]["denominator"] == 3
    assert env.batches.history()["total"] == 1 and env.research.history()["total"] == 0


def test_restart_fails_unfinished_segments_and_keeps_completed_ones(env):
    batch_id = submit(env)
    segments = env.batches.get(batch_id)["segments"]
    runs = research_tables.runs
    with env.engine.begin() as con:  # a crash in the middle of the batch
        con.execute(update(runs).where(runs.c.id == segments[1]["run_id"]).values(status="running", result=None))
        con.execute(update(runs).where(runs.c.id == segments[2]["run_id"]).values(status="queued", result=None))
    assert env.batches.get(batch_id)["status"] == "running"
    env.research.recover()
    batch = env.batches.get(batch_id)
    assert batch["status"] == "partial"
    assert [s["status"] for s in batch["segments"]] == ["completed", "failed", "failed"]
    assert batch["segments"][0]["metrics"] == segments[0]["metrics"]


def test_retry_after_a_later_sync_runs_but_a_correction_in_range_fails_it(env):
    env.boom.add(S[4])
    batch_id = submit(env)
    env.boom.clear()
    later_sync(env.engine, S[7])  # only after the second segment's next session
    env.batches.retry(batch_id, 2, str(uuid4()))
    assert env.jobs.wait_until_idle()
    assert env.batches.get(batch_id)["segments"][1]["status"] == "completed"

    env.boom.add(S[4])
    batch_id = submit(env)
    env.boom.clear()
    bars = market_tables.daily_bars
    with env.engine.begin() as con:
        con.execute(update(bars).where(bars.c.code == "13010", bars.c.date == S[3]).values(close=Decimal("1111")))
    env.batches.retry(batch_id, 2, str(uuid4()))
    assert env.jobs.wait_until_idle()
    segment = env.batches.get(batch_id)["segments"][1]
    assert segment["status"] == "failed" and len(segment["attempts"]) == 2
    assert "已变化" in segment["error"]


def test_a_segment_failed_for_missing_bars_runs_once_they_are_filled(env):
    bars = market_tables.daily_bars
    with env.engine.begin() as con:
        gone = [dict(r) for r in con.execute(select(bars).where(bars.c.code != "TOPIX", bars.c.date == S[4]))
                .mappings()]
        con.execute(bars.delete().where(bars.c.code != "TOPIX", bars.c.date == S[4]))
    batch_id = submit(env, SEGMENTS[:2])
    segment = env.batches.get(batch_id)["segments"][1]
    assert segment["status"] == "failed" and "缺少股票行情" in segment["error"]
    with env.engine.begin() as con:  # the sync fills the missing session
        con.execute(bars.insert(), gone)
    env.batches.retry(batch_id, 2, str(uuid4()))
    assert env.jobs.wait_until_idle()
    segment = env.batches.get(batch_id)["segments"][1]
    assert segment["status"] == "completed", segment["error"]
    # From now on the filled data is what this segment was run on.
    with env.engine.begin() as con:
        con.execute(update(bars).where(bars.c.code == "13010", bars.c.date == S[3]).values(close=Decimal("1111")))
    env.boom.add(S[4])
    batch_id = submit(env, SEGMENTS[:2])
    env.boom.clear()
    with env.engine.begin() as con:
        con.execute(update(bars).where(bars.c.code == "13010", bars.c.date == S[3]).values(close=Decimal("1100")))
    env.batches.retry(batch_id, 2, str(uuid4()))
    assert env.jobs.wait_until_idle()
    segment = env.batches.get(batch_id)["segments"][1]
    assert segment["status"] == "failed" and "已变化" in segment["error"]


def test_rejected_batches_write_nothing(env):
    empty = rows(env.engine)
    too_many = [SegmentSpec(S[1], S[1])] * (MAX_BATCH_RUNS + 1)
    with pytest.raises(ValueError, match=f"所选 {MAX_BATCH_RUNS + 1} 段超过单批上限 {MAX_BATCH_RUNS}"):
        submit(env, too_many)
    with pytest.raises(ValueError):
        submit(env, [])
    invalid = [SegmentSpec(S[0], S[1]), SegmentSpec(S[3], S[5]), SegmentSpec(S[6], S[5])]
    with pytest.raises(ValueError) as error:
        submit(env, invalid)
    assert S[0].isoformat() in str(error.value) and "预热期" in str(error.value)
    assert S[6].isoformat() in str(error.value) and "晚于" in str(error.value)
    assert S[3].isoformat() not in str(error.value)
    with pytest.raises(LookupError):
        env.batches.submit(source_account_id=999, entry_above=.5, exit_below=-.1, segments=SEGMENTS,
                           key=str(uuid4()))

    def stale():
        raise StaleInput("行情已变化")
    with pytest.raises(StaleInput):
        submit(env, precheck=stale)
    assert rows(env.engine) == empty
    assert env.jobs.current() is None


def test_busy_lock_and_request_keys(env):
    from threading import Event
    release = Event()
    env.jobs.submit(Job("sync", lambda _: (release.wait(3), JobOutcome())[1]))
    try:
        with pytest.raises(JobsBusy):
            env.batches.submit(source_account_id=env.source, entry_above=.5, exit_below=-.1, segments=SEGMENTS,
                               key=str(uuid4()))
    finally:
        release.set()
        assert env.jobs.wait_until_idle()
    assert rows(env.engine) == [0, 0, 0, 0]
    key = str(uuid4())
    batch_id = submit(env, key=key)
    assert submit(env, key=key) == batch_id
    with pytest.raises(ValueError, match="请求标识"):
        submit(env, SEGMENTS[:1], key=key)


@pytest.mark.parametrize("finished", [True, False], ids=["rival-finished", "rival-running"])
def test_same_batch_or_retry_sent_twice_at_once_is_accepted_once(env, monkeypatch, finished):
    env.boom.add(S[4])
    key, first = str(uuid4()), []
    rival_first(monkeypatch, env.jobs, lambda: first.append(env.batches.submit(
        source_account_id=env.source, entry_above=.5, exit_below=-.1, segments=SEGMENTS, key=key)),
        finished=finished)
    batch_id = submit(env, key=key)
    assert batch_id == first[0]
    assert rows(env.engine)[:3] == [1, 3, 3]

    env.boom.clear()
    key, first = str(uuid4()), []
    rival_first(monkeypatch, env.jobs, lambda: first.append(env.batches.retry(batch_id, 2, key)), finished=finished)
    assert env.batches.retry(batch_id, 2, key) == first[0]
    assert env.jobs.wait_until_idle()
    assert [a["run_id"] for a in env.batches.get(batch_id)["segments"][1]["attempts"]][1:] == first


def test_batches_remember_their_discovery_and_selection(env):
    selection = {"interval_ids": [1, 2, 3], "candidate_count": 4}
    batch_id = submit(env, discovery_id="d1", selection=selection, classification_fingerprint={"sha256": "x"})
    batch = env.batches.get(batch_id)
    assert (batch["discovery_id"], batch["selection"], batch["classification_fingerprint"]) == ("d1", selection, {"sha256": "x"})
    assert [s["interval_id"] for s in batch["segments"]] == [1, 2, 3]
    assert env.batches.for_discovery("d1") == [
        {"id": batch_id, "created_at": batch["created_at"], "selection": selection, "status": "completed"}]
    assert env.batches.for_discovery("other") == []
    listed = env.batches.history()["batches"][0]
    assert (listed["id"], listed["status"], listed["segments"], listed["completed"]) == (batch_id, "completed", 3, 3)


def segment(position, status, total=None, excess=None, sessions=5):
    return {"position": position, "start_date": f"2026-0{position}-01", "end_date": f"2026-0{position}-07",
            "status": status, "metrics": None if status != "completed" else
            {"total_return": total, "excess_return": excess, "sessions": sessions}}


def test_distribution_weighs_completed_segments_equally_and_counts_ties_apart():
    spread = distribution([
        segment(1, "completed", .10, .02), segment(2, "completed", 0.0, 0.0), segment(3, "completed", -.05, -.01),
        segment(4, "completed", .02, 0.0), segment(5, "failed"), segment(6, "running"), segment(7, "queued")])
    assert spread["weighting"] == "equal_per_completed_segment"
    assert (spread["selected"], spread["completed"], spread["failed"], spread["unfinished"],
            spread["denominator"]) == (7, 4, 1, 2, 4)
    assert spread["returns"] == [.10, 0.0, -.05, .02]
    assert (spread["profitable"], spread["flat"], spread["losing"], spread["profitable_ratio"]) == (2, 1, 1, .5)
    assert (spread["beat_topix"], spread["tied_topix"], spread["behind_topix"], spread["beat_ratio"]) == (1, 2, 1, .25)
    assert spread["median_return"] == pytest.approx(.01)
    assert spread["median_excess"] == 0
    assert spread["worst"] == {"position": 3, "start_date": "2026-03-01", "end_date": "2026-03-07",
                               "total_return": -.05}
    assert spread["worst_excess"]["position"] == 3 and spread["worst_excess"]["excess_return"] == -.01
    assert spread["coverage"] == {"sessions": 20, "first": "2026-01-01", "last": "2026-04-07",
                                  "ranges": [["2026-01-01", "2026-01-07"], ["2026-02-01", "2026-02-07"],
                                             ["2026-03-01", "2026-03-07"], ["2026-04-01", "2026-04-07"]]}


def test_distribution_without_completed_segments_has_no_ratios():
    spread = distribution([segment(1, "failed"), segment(2, "running")])
    assert (spread["denominator"], spread["failed"], spread["unfinished"]) == (0, 1, 1)
    assert spread["returns"] == [] and spread["median_return"] is None and spread["median_excess"] is None
    assert spread["profitable_ratio"] is None and spread["beat_ratio"] is None
    assert spread["worst"] is None and spread["worst_excess"] is None
    assert spread["coverage"] == {"sessions": 0, "first": None, "last": None, "ranges": []}
