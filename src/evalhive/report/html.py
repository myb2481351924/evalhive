"""Self-contained HTML report (inline CSS, no external assets -- opens anywhere)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.compare import GateDecision
from ..core.results import RunResult

_TPL_DIR = Path(__file__).parent / "templates"

_env = Environment(loader=FileSystemLoader(_TPL_DIR), autoescape=select_autoescape(["html"]))


def to_html(result: RunResult, decision: GateDecision | None = None) -> str:
    # metric breakdown: avg score per (provider, metric)
    buckets: dict[str, dict[str, list[float]]] = {}
    for e in result.results:
        for m in e.metrics:
            buckets.setdefault(e.provider_id, {}).setdefault(m.metric, []).append(m.score)
    avgs = {
        pid: {mn: sum(v) / len(v) for mn, v in metrics.items()} for pid, metrics in buckets.items()
    }
    tpl = _env.get_template("report.html.j2")
    return tpl.render(
        result=result,
        decision=decision,
        summaries=result.summary(),
        breakdown=avgs,
    )
