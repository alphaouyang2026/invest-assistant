"""The model experiment API (ticket 06a): registering is a job, GETs only
read what it stored, refusals come back as 404/409/422."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import NoResultFound, OperationalError

from app.config import Settings
from app.experiments import service as service_module
from app.main import create_app
from tests.account_market import fake_client
from tests.experiment_market import SESSIONS, TEST_FROM, request, topix_walk, walks


def test_register_poll_browse_retry_and_refusals(migrated_database):
    app = create_app(Settings(_env_file=None), client=fake_client(walks(), topix=topix_walk(), sessions=SESSIONS),
                     today=lambda: SESSIONS[-1])
    with TestClient(app) as client:
        app.state.market.sync()
        defaults = client.get("/api/experiments/defaults").json()
        assert defaults["defaults"]["trainer"] == "ridge_v1" and defaults["trainers"]["ridge_v1"] == {"alpha": 1.0}
        assert defaults["unsupported_actions"] == ["target_weight", "gross_exposure"]
        assert defaults["viewed_through"] is None and defaults["task"]["label_sessions"] == 6
        assert defaults["defaults"]["stress_bps"] == [10, 25, 50]
        assert (defaults["defaults"]["min_training_samples"], defaults["defaults"]["min_labelled_days"]) == (20_000, 24)

        body = {**request(), "request_key": str(uuid4())}
        response = client.post("/api/experiments", json=body)
        assert response.status_code == 202, response.text
        experiment_id = response.json()["id"]
        assert app.state.jobs.wait_until_idle(60)
        assert client.post("/api/experiments", json=body).json()["id"] == experiment_id

        detail = client.get(f"/api/experiments/{experiment_id}").json()
        assert detail["status"] == "completed", detail["error"]
        assert "request_key" not in detail and "request" not in detail
        assert detail["contract"]["test_from"] == TEST_FROM.isoformat()
        assert detail["report"]["evidence"]["status"] == "exploratory"
        assert detail["error_code"] is None and len(detail["data_read"]["sources"]) == 4
        assert [m["label"] for m in detail["report"]["models"]] == ["主模型", "对照 1"]
        assert detail["contract"]["stress"]["scenarios"][0] == {"extra_bps": "10", "slippage": "0.002"}
        assert [r["scenario"] for r in detail["report"]["replays"]] == ["base", "stress", "stress", "stress", "base"]
        assert [(f["model"], f["fold"]) for f in detail["fold_results"]] == [
            ("model", 1), ("model", 2), ("model", 3), ("baseline_1", 1), ("baseline_1", 2), ("baseline_1", 3)]
        assert len(detail["fold_results"][0]["artifact"]["state"]["coef"]) == 10
        assert detail["fold_results"][-1]["artifact"]["state"] == {}
        listed = client.get("/api/experiments").json()
        assert listed["total"] == 1 and listed["experiments"][0]["evidence_status"] == "exploratory"
        assert listed["experiments"][0]["error_code"] is None

        replay = client.get(f"/api/experiments/{experiment_id}/replays/1").json()
        assert len(replay["result"]["nav"]) == 30 and "cash" in replay["result"]["nav"][0]
        page = client.get(f"/api/experiments/{experiment_id}/replays/1/orders?page_size=1").json()
        assert page["total"] > 1 and len(page["orders"]) == 1
        days = client.get(f"/api/experiments/{experiment_id}/replays/1/days?decision_only=true&page_size=2").json()
        assert days["total"] == 6 and len(days["days"]) == 2 and len(days["days"][0]["top_scores"]) == 12
        stressed = client.get(f"/api/experiments/{experiment_id}/replays/2/days?page_size=100").json()
        assert stressed["total"] == 30  # a stress replay keeps its days too
        assert client.get(f"/api/experiments/{experiment_id}/replays/9").status_code == 404
        scores = client.get(f"/api/experiments/{experiment_id}/scores/model/{TEST_FROM.isoformat()}").json()
        assert [s["rank"] for s in scores["scores"]] == list(range(1, 13))
        assert client.get(f"/api/experiments/{experiment_id}/scores/model/{SESSIONS[101].isoformat()}").status_code == 404
        whole = client.get(f"/api/experiments/{experiment_id}/folds/model/1/artifact")
        assert whole.status_code == 200 and whole.json()["trainer"] == "ridge_v1" and "coef" in whole.json()["state"]
        assert client.get(f"/api/experiments/{experiment_id}/folds/model/9/artifact").status_code == 404
        assert client.get(f"/api/experiments/{experiment_id}/folds/nobody/1/artifact").status_code == 404

        retried = client.post(f"/api/experiments/{experiment_id}/retry", json={"request_key": str(uuid4())})
        assert retried.status_code == 422 and "失败" in retried.json()["detail"]
        assert client.get("/api/experiments/missing").status_code == 404
        refused = client.post("/api/experiments", json={**body, "request_key": str(uuid4()),
                                                        "actions": ["disposition", "priority", "target_weight"]})
        assert refused.status_code == 422 and "目标权重" in refused.json()["detail"]
        assert client.post("/api/experiments", json={**body, "request_key": str(uuid4()),
                                                      "test_from": "2026-05-23"}).status_code == 422
        assert client.get("/api/experiments").json()["total"] == 1


@pytest.mark.parametrize("error", [
    OperationalError("SELECT 1", {}, Exception("disk I/O error")),  # carries a code of its own, "e3q8"
    NoResultFound(),                                                # carries code None
], ids=["operational_error", "no_result"])
def test_any_other_failure_is_kept_as_an_error_whatever_code_it_carries(migrated_database, monkeypatch, error):
    """Neither missing data nor a changed input: the attempt fails as
    `error`, not as whatever `code` the exception brings, and the list and
    the detail still read it."""
    def fails(*args, **kwargs):
        raise error

    monkeypatch.setattr(service_module, "feature_table", fails)
    app = create_app(Settings(_env_file=None), client=fake_client(walks(), topix=topix_walk(), sessions=SESSIONS),
                     today=lambda: SESSIONS[-1])
    with TestClient(app) as client:
        app.state.market.sync()
        response = client.post("/api/experiments", json={**request(), "request_key": str(uuid4())})
        assert response.status_code == 202, response.text
        experiment_id = response.json()["id"]
        assert app.state.jobs.wait_until_idle(60)

        detail = client.get(f"/api/experiments/{experiment_id}")
        assert detail.status_code == 200, detail.text
        assert (detail.json()["status"], detail.json()["error_code"]) == ("failed", "error")
        listed = client.get("/api/experiments")
        assert listed.status_code == 200, listed.text
        assert listed.json()["experiments"][0]["error_code"] == "error"
