"""Manual-range research: durable jobs, isolated ledger, frozen reports.

Only this module knows research persistence. Trading itself is replay_day,
the exact same function used by Accounts.advance.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from filelock import FileLock, Timeout
from sqlalchemy import Connection, insert, select, update, func

from app.accounts import tables
from app.accounts import research_tables as db
from app.accounts.accounts import _Prices, _rules, replay_day
from app.accounts.ledger import Ledger
from app.accounts.records import FILLED
from app.jobs import Job, JobOutcome, LOCK_FILE, Progress
from app.market_data import EXEC_CLOSE
from app.strategies import STRATEGY_DEFAULTS, build_strategy


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def _code_version():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    lock = root.parent / "uv.lock"
    if lock.exists():
        digest.update(lock.read_bytes())
    return "sha256:" + digest.hexdigest()


class Research:
    def __init__(self, engine, market, jobs, runtime_dir, *, strategies=build_strategy):
        self._engine, self._market, self._jobs = engine, market, jobs
        self._dir, self._strategies = Path(runtime_dir), strategies

    def sources(self):
        with self._engine.connect() as con:
            rows = con.execute(select(tables.paper_accounts).where(
                tables.paper_accounts.c.strategy == "technical_rating_v1").order_by(tables.paper_accounts.c.id))
            return [{"id": r["id"], "name": r["name"], "config": self._config(dict(r))}
                    for r in rows.mappings()]

    @staticmethod
    def _config(source):
        return _json({key: source[key] for key in
                      ("name", "strategy", "strategy_params", "portfolio_rules", "costs", "start_date")})

    def recover(self):
        """Never mark another live process's run interrupted."""
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(self._dir / LOCK_FILE, timeout=0):
                self._interrupt_stale()
        except Timeout:
            pass

    def _interrupt_stale(self):
        with self._engine.begin() as con:
            con.execute(update(db.runs).where(db.runs.c.status.in_(["queued", "running"])).values(
                status="failed", error="服务中断，结果未完成；请显式重试（将创建新运行）", finished_at=_now()))

    def _existing(self, key, request):
        with self._engine.connect() as con:
            row = con.execute(select(db.runs).where(db.runs.c.request_key == key)).mappings().one_or_none()
        if row:
            if row["request"] != request:
                raise ValueError("请求标识已用于不同参数，请重新提交")
            return row["id"]
        return None

    def submit(self, request, key, *, retry_of=None):
        try:
            request = _json(request)
        except ValueError:
            raise ValueError("策略参数必须是有限数值") from None
        if retry_of:
            original = self.get(retry_of)
            if original["status"] != "failed":
                raise ValueError("只有失败的运行可以重试")
            with self._engine.connect() as con:
                if con.execute(select(db.batch_attempts.c.run_id).where(
                        db.batch_attempts.c.run_id == retry_of)).first():
                    raise ValueError("该运行属于研究批次，请在批次中重试此段")
            request = {"retry_of": retry_of}
        if existing := self._existing(key, request):
            return existing
        run_id = uuid.uuid4().hex

        def prepare():
            # Jobs holds the cross-process writer lock before invoking prepare.
            self._interrupt_stale()
            if retry_of:
                config = original["config"]
            else:
                config = self.frozen_config(request["source_account_id"], request["entry_above"],
                                            request["exit_below"], request["start_date"], request["end_date"])
            self._validate(config)
            with self._engine.begin() as con:
                self._insert_run(con, run_id, key, request, config, retry_of)

        self._jobs.submit(Job("research", lambda progress: self._execute(run_id, progress)), prepare=prepare)
        return run_id

    def frozen_config(self, source_account_id: int, entry_above: float, exit_below: float,
                      start_date: str | None, end_date: str | None) -> dict:
        """The source's configuration as it is now, with this run's range and
        thresholds. Reads the source; the caller validates the result."""
        with self._engine.connect() as con:
            source = con.execute(select(tables.paper_accounts).where(
                tables.paper_accounts.c.id == source_account_id)).mappings().one_or_none()
        if source is None:
            raise LookupError("来源账户不存在")
        if source["strategy"] != "technical_rating_v1":
            raise ValueError("首期只支持 technical_rating_v1")
        config = self._config(dict(source))
        config.update(source_account_id=source["id"], start_date=start_date, end_date=end_date)
        config["strategy_params"] = {
            **STRATEGY_DEFAULTS["technical_rating_v1"], **config["strategy_params"],
            "entry_above": entry_above, "exit_below": exit_below,
        }
        return config

    @staticmethod
    def _insert_run(con: Connection, run_id: str, key: str, request: dict, config: dict,
                    retry_of: str | None) -> None:
        """A queued run row, inside the caller's transaction."""
        con.execute(insert(db.runs).values(
            id=run_id, request_key=key, request=request, config=config, retry_of=retry_of,
            status="queued", created_at=_now(), progress={}, code_version=_code_version()))

    def _validate(self, config):
        for name in ("entry_above", "exit_below"):
            value = config["strategy_params"][name]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError(f"{name} 必须是 [-1,1] 内的有限数值")
        start, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
        calendar = self._market.calendar()
        if start > end:
            raise ValueError("起始日不能晚于结束日")
        if not calendar.is_session(start) or not calendar.is_session(end):
            raise ValueError("起止日期必须是已知开市日")
        strategy = self._strategies(config["strategy"], config["strategy_params"])
        before = [d for d in calendar.sessions() if d < start]
        if len(before) < strategy.warmup_sessions:
            raise ValueError(f"预热期不足，需要起始日前 {strategy.warmup_sessions} 个开市日")
        warmup = before[-strategy.warmup_sessions] if strategy.warmup_sessions else start
        required = [d for d in calendar.sessions() if warmup <= d <= end]
        frame = self._market.read(["TOPIX"], warmup, end)
        values = frame.wide(EXEC_CLOSE).reindex(required)
        if "TOPIX" not in values or any(pd.isna(v) or v <= 0 for v in values["TOPIX"]):
            raise ValueError("回测／预热区间 TOPIX 数据缺失或无效，请先补齐行情")
        try:
            calendar.next(end)
        except LookupError:
            raise ValueError("结束日后缺少开市日历，无法记录末日待执行订单，请先同步日历") from None
        return calendar, strategy, warmup

    def _set(self, run_id, **values):
        with self._engine.begin() as con:
            con.execute(update(db.runs).where(db.runs.c.id == run_id).values(**values))

    def _execute(self, run_id: str, progress: Progress, *, expect_identity: str | None = None) -> JobOutcome:
        """Replay one run. With `expect_identity`, refuse to replay once the
        input fingerprint differs from it (a batch segment's retry)."""
        self._set(run_id, status="running")
        try:
            config = self.get(run_id)["config"]
            calendar, strategy, warmup = self._validate(config)
            start, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
            days = [d for d in calendar.sessions() if start <= d <= end]
            # Universe also reads its 20-day turnover window, even with a short strategy warm-up.
            prior = [d for d in calendar.sessions() if d < start]
            identity_start = min(warmup, prior[max(0, len(prior) - 19)] if prior else start)
            identity = self._market.research_identity(identity_start, end)
            self._set(run_id, input_identity=identity)
            if expect_identity is not None and identity["sha256"] != expect_identity:
                raise ValueError("该区间的行情自本批首次运行后已变化，请重新发现并新建批次")
            if identity["missing_stock_sessions"]:
                raise ValueError("回测／预热区间缺少股票行情：" + ", ".join(identity["missing_stock_sessions"][:5]))
            universes = self._market.universe(start, end)
            codes = sorted({code for listed in universes.values() for code in listed})
            prices = _Prices(self._market.read(codes, warmup, end))
            topix = self._market.read(["TOPIX"], start, end).wide(EXEC_CLOSE)["TOPIX"]
            rules, costs, initial = _rules(config)
            ledger, points, warnings = Ledger(initial), [], []
            serial, peak = 0, initial
            for done, day in enumerate(days, 1):
                changed, found = replay_day(ledger, prices, strategy, universes, day, calendar.next(day), rules, costs)
                warnings.extend(found)
                # Same last-write-wins rule as Accounts._store, but IDs are local to this run.
                final = {r.id: r for r in changed if r.id is not None}
                stored = []
                for r in changed:
                    if r.id is None:
                        serial += 1
                        stored.append(replace(r, id=serial))
                    elif final[r.id] is r:
                        stored.append(r)
                ledger = ledger.apply(stored)
                closes = prices.closes(day, ledger.positions)
                nav = ledger.cash + sum((p.quantity * closes[p.code] for p in ledger.positions.values()), Decimal(0))
                peak = max(peak, nav)
                points.append({"date": day.isoformat(), "nav": float(nav), "nav_curve": float(nav / initial),
                               "topix_curve": float(topix[day] / topix[start]), "drawdown": float(1 - nav / peak)})
                step = {"sessions_done": done, "sessions_total": len(days), "current_session": day.isoformat()}
                self._set(run_id, progress=step)
                progress(step)
            holdings = [{"code": p.code, "quantity": p.quantity, "opened_on": p.opened_on.isoformat(),
                         "cost": float(p.cost), "close": float(closes[p.code]),
                         "value": float(p.quantity * closes[p.code])} for p in ledger.positions.values()]
            unrealised = sum((p.quantity * closes[p.code] - p.cost for p in ledger.positions.values()), Decimal(0))
            total = points[-1]["nav_curve"] - 1
            baseline = points[-1]["topix_curve"] - 1
            result = {"nav": points, "holdings": holdings,
                      "pending": [_record(r) for r in ledger.pending], "warnings": sorted(set(warnings)),
                      "total_return": total, "topix_return": baseline, "excess_return": total - baseline,
                      "max_drawdown": max(p["drawdown"] for p in points),
                      "trades": sum(r.status == FILLED and r.kind in ("buy", "sell") for r in ledger.records),
                      "fees": float(sum((r.fees for r in ledger.records), Decimal(0))),
                      "cash": float(ledger.cash), "unrealised_pnl": float(unrealised),
                      "realised_pnl": float(nav - initial - unrealised)}
            with self._engine.begin() as con:
                if ledger.records:
                    con.execute(insert(db.orders), [{"run_id": run_id, "sequence": r.id, "record": _record(r)}
                                                    for r in ledger.records])
                con.execute(update(db.runs).where(db.runs.c.id == run_id).values(
                    status="completed", result=result, finished_at=_now()))
            return JobOutcome({"run_id": run_id, "sessions": len(days)}, result["warnings"])
        except Exception as error:
            self._set(run_id, status="failed", error=str(error), finished_at=_now())
            raise

    def get(self, run_id):
        with self._engine.connect() as con:
            row = con.execute(select(db.runs).where(db.runs.c.id == run_id)).mappings().one_or_none()
        if row is None:
            raise LookupError("研究运行不存在")
        return dict(row)

    def history(self, page=1, page_size=20):
        """Manual runs only; a batch's segment runs are listed with their batch."""
        columns = [c for c in db.runs.c if c.name not in ("result", "request", "request_key")]
        manual = db.runs.c.id.not_in(select(db.batch_attempts.c.run_id))
        with self._engine.connect() as con:
            total = con.execute(select(func.count()).select_from(db.runs).where(manual)).scalar_one()
            rows = con.execute(select(*columns).where(manual).order_by(db.runs.c.created_at.desc(), db.runs.c.id)
                               .offset((page - 1) * page_size).limit(page_size)).mappings()
            return {"total": total, "page": page, "page_size": page_size, "runs": [dict(r) for r in rows]}

    def orders(self, run_id, page=1, page_size=50):
        self.get(run_id)
        with self._engine.connect() as con:
            where = db.orders.c.run_id == run_id
            total = con.execute(select(func.count()).select_from(db.orders).where(where)).scalar_one()
            records = con.execute(select(db.orders.c.record).where(where).order_by(db.orders.c.sequence.desc())
                                  .offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size, "orders": records}


def _record(record):
    return {**_json(asdict(record)), "name": None, "fees": float(record.fees),
            "fill_price": None if record.fill_price is None else float(record.fill_price),
            "cash_delta": float(record.cash_delta)}
