"""API smoke tests with an isolated SQLite file."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evalhive.api import create_app
from evalhive.storage import Store

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path: Path):
    store = Store(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    with TestClient(create_app(store)) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_trigger_and_poll_run(client):
    r = client.post(
        "/api/runs", json={"config_path": str(REPO_ROOT / "examples/rag-chat/config.yaml")}
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    for _ in range(50):
        time.sleep(0.1)
        runs = client.get("/api/runs").json()
        row = next(x for x in runs if x["id"] == run_id)
        if row["status"] != "running":
            break
    assert row["status"] == "done"
    assert row["pass_rate"] == pytest.approx(0.8)

    detail = client.get(f"/api/runs/{run_id}").json()
    assert len(detail["results"]) == 5
    assert "support-bot" in detail["summaries"]

    html = client.get(f"/api/runs/{run_id}/report.html")
    assert html.status_code == 200 and "EvalHive report" in html.text


def test_baseline_flow(client):
    r = client.post(
        "/api/runs", json={"config_path": str(REPO_ROOT / "examples/rag-chat/config.yaml")}
    )
    run_id = r.json()["run_id"]
    for _ in range(50):
        time.sleep(0.1)
        if client.get("/api/runs").json()[0]["status"] == "done":
            break
    assert client.get("/api/baseline").status_code == 404
    assert client.post("/api/baseline", json={"run_id": run_id}).json() == {"ok": True}
    assert client.get("/api/baseline").json()["id"] == run_id

    diff = client.get("/api/diff", params={"baseline": run_id, "current": run_id}).json()
    assert diff["drift"] == 0.0
    assert client.get("/api/trend").json()[0]["is_baseline"] is True


def test_bad_config_path(client):
    assert client.post("/api/runs", json={"config_path": "nowhere.yaml"}).status_code == 422
