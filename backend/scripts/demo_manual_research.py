"""Real-data API smoke run on a temporary SQLite backup, never on user data.

Run from backend: uv run python scripts/demo_manual_research.py ../var/invest.db
Prints the retained temporary directory and two saved report summaries.
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


def main():
    source = Path(sys.argv[1]).resolve()
    target = Path(tempfile.mkdtemp(prefix="invest-research-demo-")) / "invest.db"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    os.environ["DATABASE_PATH"] = str(target)
    upgrade_to_head()
    settings = Settings(_env_file=None)
    app = create_app(settings)
    print(json.dumps({"isolated_database": str(target)}), flush=True)
    with TestClient(app) as client:
        account = client.get("/api/research/sources").json()[0]["id"]
        for entry in (.5, .6):
            started = time.monotonic()
            response = client.post("/api/research/runs", json={
                "request_key": str(uuid4()), "source_account_id": account,
                "start_date": "2026-09-01", "end_date": "2026-09-28",
                "entry_above": entry, "exit_below": -.1,
            })
            assert response.status_code == 202, response.text
            run_id = response.json()["id"]
            while not app.state.jobs.wait_until_idle(timeout=1):
                pass
            detail = client.get(f"/api/research/runs/{run_id}").json()
            assert detail["status"] == "completed", detail
            summary = {k: v for k, v in detail["result"].items() if k not in ("nav", "holdings", "pending")}
            print(json.dumps({"run_id": run_id, "entry": entry, "seconds": round(time.monotonic() - started, 2),
                              "input": detail["input_identity"], "result": summary}, ensure_ascii=False), flush=True)
            assert client.get(f"/api/research/runs/{run_id}/orders?page_size=1").status_code == 200
        print("Both runs persisted; refresh via /accounts/research?run=<run_id> with this isolated DATABASE_PATH.")


if __name__ == "__main__":
    main()
