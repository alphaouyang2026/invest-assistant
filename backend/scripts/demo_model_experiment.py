"""06a real-data demo: a model experiment registered and read back through
the HTTP API on a copy of the database — never the real one.

Run from backend:
    uv run python scripts/demo_model_experiment.py ../var/invest.db \
        [--copy-dir DIR] [--test-from 2023-01-04] [--test-to 2026-10-16] [--keep]

Copies the database with SQLite's backup API, the source opened read-only,
into a new directory under DIR (default: the system's temporary directory),
migrates the copy and points the app at it — so the job lock and job log
are the copy's, beside it, and the real service's are never touched. The
copy is never synced either: the app gets a J-Quants client that refuses
every call, so the evening sync timer cannot fetch into it.

Registers the default contract (Ridge as the smoke-test model, short
reversal as the rule baseline, ADV20 cap 5%, stress scenarios adding
10/25/50 bps a side to the base slippage) over the test span, prints the
job's progress, then JSON lines: wall time and the stages' timings; the
frozen contract's hash, viewed_through, input fingerprint and code
identity; what the attempt read and when; the folds and which were already
seen; each fold's artifact with its hash recomputed from the stored JSON,
and the first fold's Ridge coefficients; each model's failed folds, Rank IC
and coverage; the benchmarks; every replay's figures (returns, drawdown,
turnover, fill rate, cash share, orders against ADV20, by fold and by
year); the evidence status with its reasons; every replay's day-by-day
decisions tallied, and the first two days in full; each remaining endpoint
read once; and how much the experiment's rows take in the copy.
Removes the copy at the end unless --keep (then it is there for a page
session: DATABASE_PATH=<copy> and open /accounts/research?mode=experiment).
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

PAGE = 100  # the largest page the API serves


def show(value) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


class NoSync:
    """The copy's J-Quants client: anything fetched fails before the network."""

    def __getattr__(self, name):
        raise RuntimeError("演示用的数据库副本不同步行情")


def copy_database(source: Path, parent: Path | None) -> Path:
    if not source.is_file():
        sys.exit(f"找不到数据库：{source}")
    directory = Path(tempfile.mkdtemp(prefix="invest-experiment-demo-", dir=parent)).resolve()
    if directory == source.parent:  # the real job lock lives beside the real database
        sys.exit("副本不能放在原数据库所在的目录")
    target = directory / "invest.db"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    return target


def summary(metrics: dict) -> dict:
    keys = ("sessions", "total_return", "topix_return", "excess_return", "annualised_return", "max_drawdown",
            "sharpe", "annual_turnover", "trades", "fees", "average_cash_share", "average_holding_sessions",
            "win_rate", "closed_positions")
    return {**{k: metrics[k] for k in keys}, "fill_rate": metrics["fill_rate"], "adv20": metrics["adv20"]}


def every_day(client, base: str) -> list[dict]:
    days, page = [], 1
    while True:
        found = client.get(f"{base}/days?page={page}&page_size={PAGE}")
        assert found.status_code == 200, found.text[:500]
        body = found.json()
        days += body["days"]
        if len(days) >= body["total"]:
            return days
        page += 1


def tally(days: list[dict]) -> dict:
    """What a base replay decided over all its days, counted."""
    held = Counter((d["disposition"], ",".join(d["reason_codes"])) for day in days
                   for d in day["holdings_decisions"])
    orders = Counter((o["kind"], ",".join(o["reason_codes"]), o["status"], o["outcome_reason"])
                     for day in days for o in day["orders"])
    constraints = Counter()
    for day in days:
        for reason, count in day["constraints"]["skipped"].items():
            constraints[f"skipped:{reason}"] += count
        for key in ("adv20_capped", "ranked_out", "unplaced_candidates"):
            constraints[key] += day["constraints"][key]
    decision_days = [day for day in days if day["decision_day"]]
    return {
        "days": len(days), "decision_days": len(decision_days),
        "model_unavailable_days": sum(day["model_available"] is False for day in decision_days),
        "holdings_decisions": {f"{d or 'none'}:{r}": n for (d, r), n in sorted(held.items(), key=str)},
        "orders": {":".join(str(part) for part in key): n for key, n in sorted(orders.items(), key=str)},
        "constraints": dict(sorted(constraints.items())),
        "fully_in_cash_days": sum(not day["holdings"] for day in days),
        "max_holdings": max(len(day["holdings"]) for day in days),
    }


def brief(day: dict) -> dict:
    """One day's record with its lists cut short."""
    return {**{k: day[k] for k in ("date", "decision_day", "model_available", "fold", "universe", "scored",
                                   "candidates", "cash", "nav", "constraints")},
            "holdings_decisions": day["holdings_decisions"][:5], "orders": day["orders"][:12],
            "executions": day["executions"][:12], "target": day["target"], "holdings": day["holdings"],
            "top_scores": day["top_scores"][:5]}


def storage(database: Path, experiment_id: str) -> dict:
    """The experiment's rows in the copy: how many, and their stored text in bytes, table by table (the
    days and orders by replay)."""
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as con:
        def rows(sql: str) -> list:
            return con.execute(sql, (experiment_id,)).fetchall()
        found = {
            "days_by_replay": {position: {"rows": n, "bytes": size} for position, n, size in rows(
                "SELECT position, count(*), sum(length(record)) FROM model_experiment_days "
                "WHERE experiment_id = ? GROUP BY position ORDER BY position")},
            "orders_by_replay": {position: {"rows": n, "bytes": size} for position, n, size in rows(
                "SELECT position, count(*), sum(length(record)) FROM model_experiment_orders "
                "WHERE experiment_id = ? GROUP BY position ORDER BY position")},
            "replays_bytes": rows("SELECT sum(length(result)) FROM model_experiment_replays "
                                  "WHERE experiment_id = ?")[0][0],
            "scores_bytes": rows("SELECT sum(length(scores)) FROM model_experiment_scores WHERE experiment_id = ?")[0][0],
            "folds_bytes": rows("SELECT sum(length(artifact)) FROM model_experiment_folds WHERE experiment_id = ?")[0][0],
            "experiment_bytes": rows("SELECT length(contract) + length(report) + length(data_read) "
                                     "FROM model_experiments WHERE id = ?")[0][0],
        }
    found["days_bytes"] = sum(part["bytes"] for part in found["days_by_replay"].values())
    found["orders_bytes"] = sum(part["bytes"] for part in found["orders_by_replay"].values())
    found["total_bytes"] = sum(found[key] for key in ("days_bytes", "orders_bytes", "replays_bytes", "scores_bytes",
                                                      "folds_bytes", "experiment_bytes"))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("--copy-dir", type=Path, default=None)
    parser.add_argument("--test-from", default="2023-01-04")
    parser.add_argument("--test-to", default="2026-10-16")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    target = copy_database(args.source.resolve(), args.copy_dir)
    # Before the app is imported: app.main builds a module-level app from the environment.
    os.environ["DATABASE_PATH"] = str(target)
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.experiments import ModelArtifact
    from app.main import create_app
    from app.migrate import upgrade_to_head

    upgrade_to_head()
    app = create_app(Settings(_env_file=None), client=NoSync())
    show({"isolated_database": str(target)})
    try:
        with TestClient(app) as client:
            defaults = client.get("/api/experiments/defaults").json()
            show({"viewed_through_now": defaults["viewed_through"], "task": defaults["task"]["name"],
                  "features": defaults["features"]["version"]})

            started = time.monotonic()
            response = client.post("/api/experiments", json={
                "request_key": str(uuid4()), "test_from": args.test_from, "test_to": args.test_to,
                "name": "Ridge 冒烟（真实数据演示）"})
            assert response.status_code == 202, response.text
            experiment_id = response.json()["id"]
            base = f"/api/experiments/{experiment_id}"
            while not app.state.jobs.wait_until_idle(timeout=15):
                show({"seconds": round(time.monotonic() - started), "progress": client.get(base).json()["progress"]})
            wall = time.monotonic() - started

            detail = client.get(base)
            assert detail.status_code == 200, detail.text[:500]
            detail = detail.json()
            assert detail["status"] == "completed", detail["error"]
            report, contract = detail["report"], detail["contract"]
            show({"experiment": experiment_id, "wall_seconds": round(wall, 1),
                  "timings": {k: (round(v, 1) if isinstance(v, float) else
                                  [round(x, 1) for x in v] if isinstance(v, list) else
                                  {m: round(x, 1) for m, x in v.items()}) for k, v in report["timings"].items()}})
            show({"contract_hash": detail["contract_hash"], "viewed_through": contract["viewed_through"],
                  "test": [contract["test_from"], contract["test_to"]], "folds": contract["folds"],
                  "policy": {k: contract["policy"][k] for k in ("strategy", "anchor", "rebalance_sessions",
                                                                 "max_holding_sessions")},
                  "portfolio_rules": contract["portfolio_rules"], "costs": contract["costs"],
                  "stress": contract["stress"], "model": contract["model"],
                  "baselines": contract["baselines"], "minimums": contract["minimums"],
                  "code_version": detail["code_version"],
                  "input_fingerprint": {k: detail["input_fingerprint"][k] for k in ("sha256", "from", "through",
                                                                                    "rows")}})
            show({"data_read": detail["data_read"]})
            show({"sessions": report["sessions"], "decision_days": report["decision_days"],
                  "read_from": report["read_from"],
                  "folds": [[f["number"], f["train_from"], f["train_to"], f["test_from"], f["test_to"], f["viewed"]]
                            for f in report["folds"]]})

            # Every artifact's hash, recomputed from the JSON the experiment kept.
            checked = Counter()
            for fold in detail["fold_results"]:
                if fold["artifact"] is None:
                    checked[f"{fold['model']}:failed"] += 1
                    continue
                same = ModelArtifact.from_dict(fold["artifact"]).hash() == fold["artifact_hash"]
                checked[f"{fold['model']}:{'hash_ok' if same else 'hash_MISMATCH'}"] += 1
            first = next(f for f in detail["fold_results"] if f["model"] == "model" and f["artifact"])
            state = first["artifact"]["state"]
            show({"artifacts": dict(checked),
                  "samples": {m: [f["samples"] for f in detail["fold_results"] if f["model"] == m]
                              for m in sorted({f["model"] for f in detail["fold_results"]})},
                  "first_model_artifact": {
                      "fold": first["fold"], "trainer": first["artifact"]["trainer"],
                      "params": first["artifact"]["params"], "train_cutoff": first["artifact"]["train_cutoff"],
                      "samples": first["artifact"]["samples"], "hash": first["artifact_hash"],
                      "intercept": state["intercept"],
                      "coef": dict(zip(state["features"], state["coef"], strict=True))}})

            for model in report["models"]:
                d = model["diagnostics"]
                show({"model": model["key"], "label": model["label"], "trainer": model["trainer"],
                      "failed_folds": model["failed_folds"],
                      **{k: d[k] for k in ("decision_days", "unavailable_days", "ic_days", "ic_mean", "ic_std",
                                           "coverage_mean", "coverage_min")},
                      "ic_by_fold": [[f["fold"], f["ic_mean"]] for f in d["folds"]]})
            pool = report["benchmarks"]["eligible_equal_weight"]
            show({"topix_price": report["benchmarks"]["topix_price"]["total_return"],
                  "eligible_equal_weight": pool["total_return"], "pool_periods": len(pool["periods"])})
            for replay in report["replays"]:
                show({"replay": replay["position"], "model": replay["model"], "label": replay["model_label"],
                      "scenario": replay["scenario"], "extra_bps": replay["extra_bps"],
                      "slippage": replay["costs"]["slippage"], **summary(replay["metrics"]),
                      "folds": [None if f is None else [f["fold"], f["net_return"], f["excess_return"]]
                                for f in replay["folds"]],
                      "years": [[y["year"], y["net_return"], y["excess_return"]] for y in replay["years"]]})
            show({"evidence": report["evidence"], "warnings": report["warnings"][:10]})

            # The day-by-day decisions of every replay, stress ones too, then the first two days in full.
            for replay in report["replays"]:
                days = every_day(client, f"{base}/replays/{replay['position']}")
                show({"replay": replay["position"], "model": replay["model"], "day_by_day": tally(days)})
                if replay["position"] == 1:
                    for day in days[:2]:
                        show({"first_days": brief(day)})

            stress = next(r["position"] for r in report["replays"] if r["scenario"] == "stress")
            first_day = report["models"][0]["diagnostics"]["days"][0]["date"]
            for path, expected in ((f"{base}/replays/1", 200), (f"{base}/replays/1/orders?page_size=5", 200),
                                   (f"{base}/replays/{stress}/days", 200),
                                   (f"{base}/scores/model/{first_day}", 200), ("/api/experiments", 200)):
                found = client.get(path)
                assert found.status_code == expected, (path, found.status_code, found.text[:500])
                show({"get": path, "status": found.status_code, "bytes": len(found.content)})
            show({"orders_total": client.get(f"{base}/replays/1/orders?page_size=1").json()["total"]})
            show({"storage": storage(target, experiment_id)})
    finally:
        if args.keep:
            show({"kept": str(target)})
        else:
            shutil.rmtree(target.parent)
            show({"removed": str(target.parent)})


if __name__ == "__main__":
    main()
