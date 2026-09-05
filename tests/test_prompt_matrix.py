"""Prompt variant matrix: providers x prompts x cases."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evalhive.config.loader import ConfigError, load_cases, load_config
from evalhive.core.compare import diff_runs
from evalhive.core.results import RunResult
from evalhive.core.runner import run_evaluation
from evalhive.report.html import to_html

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _run_matrix():
    cfg, base = load_config(EXAMPLES / "prompt-matrix/config.yaml")
    cases = load_cases(cfg, base)
    return asyncio.run(run_evaluation(cfg, cases, base, use_cache=False)), cfg


def test_matrix_scores_per_variant():
    result, cfg = _run_matrix()
    assert len(cfg.prompts) == 2
    assert len(result.results) == 6  # 1 provider x 2 variants x 3 cases

    summaries = result.summary()
    assert set(summaries) == {"mock-model/baseline", "mock-model/cot"}
    assert summaries["mock-model/baseline"].passed == 2  # q1 wrong answer
    assert summaries["mock-model/cot"].passed == 3

    q1_base = next(e for e in result.results if e.case_id == "q1" and e.prompt_id == "baseline")
    assert q1_base.prompt.startswith("Answer the question directly:")
    q1_cot = next(e for e in result.results if e.case_id == "q1" and e.prompt_id == "cot")
    assert q1_cot.passed and "0.75" in q1_cot.response


def test_matrix_diff_uses_variant_labels():
    result, _ = _run_matrix()
    cot = RunResult(
        config_hash=result.config_hash,
        description="cot only",
        results=[e for e in result.results if e.prompt_id == "cot"],
    )
    base = RunResult(
        config_hash=result.config_hash,
        description="baseline only",
        results=[e for e in result.results if e.prompt_id == "baseline"],
    )

    report = diff_runs(base, cot)
    labels = {c.label for c in report.cases}
    assert "mock-model/cot/q1" in labels  # variant name visible in diff labels
    added = {(c.label, c.change) for c in report.cases if c.change == "added"}
    assert ("mock-model/cot/q1", "added") in added

    # same key flipping pass state shows as newly_passed with the variant label
    from evalhive.core.results import CaseEval, MetricResult

    def ce(passed: bool) -> CaseEval:
        return CaseEval(
            provider_id="m",
            prompt_id="v",
            case_id="q1",
            metrics=[MetricResult(metric="icontains", score=1.0 if passed else 0.0, passed=passed)],
        )

    old = RunResult(config_hash="old", results=[ce(False)])
    new = RunResult(config_hash="new", results=[ce(True)])
    flipped = [c for c in diff_runs(old, new).cases if c.change == "newly_passed"]
    assert [c.label for c in flipped] == ["m/v/q1"]


def test_template_without_prompt_placeholder_rejected(tmp_path: Path):
    (tmp_path / "d.jsonl").write_text('{"id":"a","prompt":"hi"}\n', encoding="utf-8")
    (tmp_path / "c.yaml").write_text(
        "providers: [{id: m, type: mock, default_response: ok}]\n"
        "prompts: [{id: v, template: 'no placeholder here'}]\n"
        "datasets: [{path: d.jsonl}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must contain"):
        load_config(tmp_path / "c.yaml")


def test_html_report_shows_variant():
    result, _ = _run_matrix()
    html = to_html(result)
    assert "mock-model/baseline" in html and "mock-model/cot" in html
