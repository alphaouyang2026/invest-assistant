"""04b-B real-data API smoke run on a temporary SQLite backup, never on user data.

Run from backend: uv run python scripts/demo_regime_research.py ../var/invest.db
Tries a few TOPIX regime filters over all TOPIX history, picks the first
that yields at least two intervals the strategy can warm up for, runs one
configuration over up to three of them as a batch, and checks the first
segment against an ordinary manual run of the same range. Prints JSON
lines; the temporary directory is kept for a page session.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.migrate import upgrade_to_head

FILTERS = [("up", None), ("down", None), ("neutral", None), ("up", "low"), ("up", "high"), ("down", "high")]
WARMUP = 260  # technical_rating_v1's default
PICK = 3


def show(value) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    source = Path(sys.argv[1]).resolve()
    target = Path(tempfile.mkdtemp(prefix="invest-regime-demo-")) / "invest.db"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    os.environ["DATABASE_PATH"] = str(target)
    upgrade_to_head()
    app = create_app(Settings(_env_file=None))
    show({"isolated_database": str(target)})

    def idle():
        while not app.state.jobs.wait_until_idle(timeout=1):
            pass

    with TestClient(app) as client:
        definition = client.get("/api/research/regimes/definition").json()
        show({"definition": definition["version"], "topix_from": definition["topix_from"],
              "topix_through": definition["topix_through"]})
        account = client.get("/api/research/sources").json()[0]["id"]

        chosen = None
        for trend, volatility in FILTERS:
            started = time.monotonic()
            response = client.post("/api/research/discoveries", json={
                "request_key": str(uuid4()), "search_from": definition["topix_from"],
                "search_to": definition["topix_through"], "trend": trend, "volatility": volatility})
            assert response.status_code == 202, response.text
            idle()
            found = client.get(f"/api/research/discoveries/{response.json()['id']}").json()
            assert found["status"] == "completed", found
            eligible = [i for i in found["intervals"] if i["sessions_before"] >= WARMUP and not i["single_day"]]
            show({"filter": [trend, volatility], "discovery": found["id"], "seconds": round(time.monotonic() - started, 2),
                  "search_sessions": found["diagnostics"]["search_sessions"],
                  "matched_sessions": found["diagnostics"]["matched_sessions"],
                  "warmup_unknown": found["diagnostics"]["warmup_unknown"], "gaps": len(found["diagnostics"]["gaps"]),
                  "candidates": len(found["intervals"]), "strategy_can_warm_up": len(eligible),
                  "single_day": sum(i["single_day"] for i in found["intervals"]),
                  "short": sum(i["short"] for i in found["intervals"])})
            if chosen is None and len(eligible) >= 2:
                # The longest few, so each segment has room for trades.
                chosen = (found, sorted(sorted(eligible, key=lambda i: -i["sessions"])[:PICK], key=lambda i: i["id"]))
        assert chosen, "no filter gave two intervals the strategy can warm up for"

        found, intervals = chosen
        started = time.monotonic()
        response = client.post("/api/research/batches", json={
            "request_key": str(uuid4()), "discovery_id": found["id"], "interval_ids": [i["id"] for i in intervals],
            "source_account_id": account, "entry_above": .5, "exit_below": -.1})
        assert response.status_code == 202, response.text
        idle()
        batch = client.get(f"/api/research/batches/{response.json()['id']}").json()
        show({"batch": batch["id"], "discovery": found["id"], "filter": found["parameters"],
              "selected": [i["id"] for i in intervals], "candidates": len(found["intervals"]),
              "status": batch["status"], "seconds": round(time.monotonic() - started, 2)})
        for s in batch["segments"]:
            show({"position": s["position"], "interval": s["interval_id"], "range": [s["start_date"], s["end_date"]],
                  "status": s["status"], "run_id": s["run_id"], "error": s["error"], "metrics": s["metrics"]})
        show({"distribution": {k: v for k, v in batch["distribution"].items() if k not in ("returns", "excess_returns")}})

        # The same range as an ordinary manual run must give the same result and ledger.
        first = next(s for s in batch["segments"] if s["status"] == "completed")
        response = client.post("/api/research/runs", json={
            "request_key": str(uuid4()), "source_account_id": account, "start_date": first["start_date"],
            "end_date": first["end_date"], "entry_above": .5, "exit_below": -.1})
        assert response.status_code == 202, response.text
        idle()
        manual = client.get(f"/api/research/runs/{response.json()['id']}").json()
        child = client.get(f"/api/research/runs/{first['run_id']}").json()
        def ledger(run):
            rows, page = [], 1
            while True:
                data = client.get(f"/api/research/runs/{run}/orders?page={page}&page_size=200").json()
                rows += [{k: v for k, v in o.items() if k != "id"} for o in data["orders"]]
                if len(rows) >= data["total"]:
                    return rows
                page += 1
        orders = [ledger(run) for run in (manual["id"], child["id"])]
        show({"manual_run": manual["id"], "batch_child": child["id"], "orders": len(orders[0]),
              "same_result": manual["result"] == child["result"], "same_orders": orders[0] == orders[1],
              "same_input": manual["input_fingerprint"]["sha256"] == child["input_fingerprint"]["sha256"]})
        print("Open /accounts/research?mode=regime&discovery=<id>&batch=<id> with this isolated DATABASE_PATH.")


if __name__ == "__main__":
    main()
