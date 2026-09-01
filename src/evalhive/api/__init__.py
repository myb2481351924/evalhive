"""FastAPI service: REST API + background eval runs + static dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config.loader import ConfigError, load_cases, load_config
from ..core.compare import diff_runs
from ..report.html import to_html
from ..storage import Store

REPO_ROOT = Path(__file__).resolve().parents[3]


class TriggerRun(BaseModel):
    config_path: str


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="EvalHive", version="0.1.0")
    store = store or Store()

    # ---- runs -------------------------------------------------------------

    @app.get("/api/runs")
    def list_runs(limit: int = 50) -> list[dict]:
        rows = store.list_runs(limit=limit)
        return [
            {
                "id": r.id,
                "label": r.label,
                "config_hash": r.config_hash,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "n_cases": r.n_cases,
                "n_passed": r.n_passed,
                "pass_rate": r.pass_rate,
                "is_baseline": bool(r.is_baseline),
            }
            for r in rows
        ]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int) -> dict:
        row = store.get_run_row(run_id)
        if not row:
            raise HTTPException(404, "run not found")
        result = store.get_run(run_id)
        if result is None:
            raise HTTPException(409, f"run is {row.status}"
                                + (f": {row.error}" if row.error else ""))
        return {
            "id": row.id,
            "label": row.label,
            "config_hash": row.config_hash,
            "created_at": row.created_at.isoformat(),
            "pass_rate": row.pass_rate,
            "is_baseline": bool(row.is_baseline),
            "summaries": {pid: s.model_dump() for pid, s in result.summary().items()},
            "results": [e.model_dump() for e in result.results],
        }

    @app.get("/api/runs/{run_id}/report.html", response_class=HTMLResponse)
    def run_html_report(run_id: int) -> str:
        result = store.get_run(run_id)
        if not result:
            raise HTTPException(404, "run not found")
        return to_html(result)

    @app.post("/api/runs")
    async def trigger_run(body: TriggerRun, background: BackgroundTasks) -> dict:
        try:
            cfg, config_dir = load_config(body.config_path)
            cases = load_cases(cfg, config_dir)
        except ConfigError as e:
            raise HTTPException(422, str(e))
        row_id = store.create_pending(label=f"api:{body.config_path}")

        async def _job() -> None:
            from ..core.runner import run_evaluation

            try:
                result = await run_evaluation(cfg, cases, config_dir, concurrency=8)
                store.finish_run(row_id, result)
            except Exception as e:  # noqa: BLE001
                store.fail_run(row_id, f"{type(e).__name__}: {e}")

        background.add_task(_job)
        return {"run_id": row_id, "status": "running"}

    # ---- baseline & diff ----------------------------------------------------

    @app.get("/api/baseline")
    def get_baseline() -> dict:
        row = store.get_baseline_row()
        if not row:
            raise HTTPException(404, "no baseline set")
        return {"id": row.id, "label": row.label, "config_hash": row.config_hash,
                "pass_rate": row.pass_rate}

    @app.post("/api/baseline")
    def set_baseline(body: dict) -> dict:
        run_id = int(body.get("run_id", 0))
        if not store.set_baseline(run_id):
            raise HTTPException(404, f"run {run_id} not found")
        return {"ok": True}

    @app.get("/api/diff")
    def runs_diff(baseline: int, current: int) -> dict:
        base = store.get_run(baseline)
        curr = store.get_run(current)
        if not base or not curr:
            raise HTTPException(404, "run not found")
        return diff_runs(base, curr).model_dump()

    @app.get("/api/trend")
    def trend(limit: int = 50) -> list[dict]:
        """Per-run points for the dashboard trend chart, oldest first."""
        out = []
        for r in reversed(store.list_runs(limit=limit)):
            result = store.get_run(r.id)
            summaries = result.summary() if result else {}
            cost = sum(s.total_cost_usd for s in summaries.values())
            lat = max((s.avg_latency_ms for s in summaries.values()), default=0.0)
            out.append({"id": r.id, "created_at": r.created_at.isoformat(),
                        "pass_rate": r.pass_rate, "cost_usd": round(cost, 4),
                        "avg_latency_ms": lat, "is_baseline": bool(r.is_baseline)})
        return out

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "db": str(store.url)}

    # ---- dashboard ----------------------------------------------------------

    static_dir = REPO_ROOT / "web" / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
