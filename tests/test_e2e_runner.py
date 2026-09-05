"""End-to-end tests: mock eval matrix, regression diff, gate exit semantics."""

from __future__ import annotations

import asyncio
from pathlib import Path

from evalhive.config.loader import load_cases, load_config
from evalhive.core.compare import diff_runs, gate_decision
from evalhive.core.results import RunResult
from evalhive.core.runner import run_evaluation

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _run(example_dir: Path) -> RunResult:
    cfg, base = load_config(example_dir / "config.yaml")
    cases = load_cases(cfg, base)
    return asyncio.run(run_evaluation(cfg, cases, base, use_cache=False))


def test_rag_chat_end_to_end():
    result = _run(EXAMPLES / "rag-chat")
    summaries = result.summary()
    assert set(summaries) == {"support-bot"}  # judge stays out of the matrix
    s = summaries["support-bot"]
    assert (s.total, s.passed, s.failed) == (5, 4, 1)
    c3 = next(e for e in result.results if e.case_id == "c3")
    judged = {m.metric: m for m in c3.metrics}
    assert judged["llm-correctness"].score == 0.4  # judge SCORE 2 -> 2/5
    assert not judged["icontains"].passed
    assert c3.latency_ms > 0 and c3.cost_usd >= 0


def test_codegen_matrix_and_gate():
    result = _run(EXAMPLES / "codegen")
    assert set(result.summary()) == {"model-a", "model-b"}
    cfg, _ = load_config(EXAMPLES / "codegen/config.yaml")
    good = _run(EXAMPLES / "rag-chat")
    assert gate_decision(result, cfg.gate).passed is False  # model-b g3 fails
    assert gate_decision(good, good_gate()).passed is True


def good_gate():
    from evalhive.config.models import GateConfig

    return GateConfig(min_pass_rate=0.8)


def test_diff_detects_regression():
    base = _run(EXAMPLES / "rag-chat")
    curr = _run(EXAMPLES / "function-calling")  # unrelated suite: cases are "added"
    report = diff_runs(base, curr)
    assert {c.change for c in report.cases} == {"added", "removed"}

    # identical runs => zero drift, not significant
    same = diff_runs(base, base)
    assert same.drift == 0.0 and not same.significant
    assert all(c.change == "unchanged_pass" or c.change == "unchanged_fail" for c in same.cases)


def test_gate_decision_reasons():
    result = _run(EXAMPLES / "rag-chat")  # 80%
    from evalhive.config.models import GateConfig

    d = gate_decision(result, GateConfig(min_pass_rate=0.9))
    assert not d.passed and "pass_rate" in d.reasons[0]
    d_ok = gate_decision(result, GateConfig(min_pass_rate=0.8))
    assert d_ok.passed and not d_ok.reasons


def test_render_failure_fails_case_not_run(tmp_path):
    """A broken prompt_template must degrade to a per-case error, never crash the run."""
    (tmp_path / "d.jsonl").write_text('{"id":"a","prompt":"hi"}\n', encoding="utf-8")
    (tmp_path / "c.yaml").write_text(
        "providers:\n  - id: m\n    type: mock\n    default_response: ok\n"
        '    prompt_template: "Answer in {style} tone: {prompt}"\n'
        "datasets: [{path: d.jsonl}]\n",
        encoding="utf-8",
    )
    cfg, base = load_config(tmp_path / "c.yaml")
    cases = load_cases(cfg, base)
    result = asyncio.run(run_evaluation(cfg, cases, base, use_cache=False))
    assert len(result.results) == 1
    e = result.results[0]
    assert not e.passed and e.error and e.error.startswith("prompt render failed")
    assert e.metrics == []
