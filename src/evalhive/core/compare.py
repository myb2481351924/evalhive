"""Run-to-run comparison: case-level diff, drift, bootstrap significance.

Why bootstrap instead of a naive pass-rate delta: eval sets are small and
LLM outputs are noisy -- a 2/20 flip may be pure chance. The paired bootstrap
over per-case pass flags gives an honest confidence interval for the drift,
which is exactly the regression-test discipline a QA platform should have.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pydantic import BaseModel

from ..config.models import GateConfig
from .results import RunResult


def load_run_result(path: str | Path) -> RunResult:
    return RunResult.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def pass_flags(result: RunResult) -> dict[tuple[str, str], int]:
    """(provider, case) -> 1/0 pass flag."""
    return {(e.provider_id, e.case_id): 1 if e.passed else 0 for e in result.results}


class CaseDiff(BaseModel):
    provider_id: str
    case_id: str
    change: str  # newly_failed | newly_passed | unchanged_pass | unchanged_fail | added | removed


class DiffReport(BaseModel):
    baseline_hash: str
    current_hash: str
    baseline_pass_rate: float
    current_pass_rate: float
    drift: float  # current - baseline
    ci_low: float  # 95% bootstrap CI of the drift (paired over common cases)
    ci_high: float
    significant: bool  # CI excludes 0
    cases: list[CaseDiff]

    @property
    def newly_failed(self) -> list[CaseDiff]:
        return [c for c in self.cases if c.change == "newly_failed"]

    @property
    def added(self) -> list[str]:
        return [f"{c.provider_id}/{c.case_id}" for c in self.cases if c.change in ("added", "removed")]


def bootstrap_drift_ci(
    base: dict[tuple[str, str], int],
    curr: dict[tuple[str, str], int],
    n_iter: int = 2000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, bool]:
    """Paired bootstrap over cases present in both runs. Returns (low, high, significant)."""
    common = sorted(set(base) & set(curr))
    if not common:
        return (0.0, 0.0, False)
    deltas = [curr[k] - base[k] for k in common]
    rng = random.Random(seed)
    stats = sorted(sum(rng.choice(deltas) for _ in deltas) / len(deltas) for _ in range(n_iter))
    alpha = (1 - ci) / 2
    low = stats[int(alpha * n_iter)]
    high = stats[min(n_iter - 1, int((1 - alpha) * n_iter))]
    return (round(low, 4), round(high, 4), low > 0 or high < 0)


def diff_runs(baseline: RunResult, current: RunResult, n_iter: int = 2000) -> DiffReport:
    base, curr = pass_flags(baseline), pass_flags(current)
    keys = sorted(set(base) | set(curr))
    cases = []
    for k in keys:
        b, c = base.get(k), curr.get(k)
        if b is None:
            change = "added"
        elif c is None:
            change = "removed"
        elif b and c:
            change = "unchanged_pass"
        elif not b and not c:
            change = "unchanged_fail"
        elif c:
            change = "newly_passed"
        else:
            change = "newly_failed"
        cases.append(CaseDiff(provider_id=k[0], case_id=k[1], change=change))
    low, high, sig = bootstrap_drift_ci(base, curr, n_iter=n_iter)
    return DiffReport(
        baseline_hash=baseline.config_hash,
        current_hash=current.config_hash,
        baseline_pass_rate=round(baseline.overall_pass_rate(), 4),
        current_pass_rate=round(current.overall_pass_rate(), 4),
        drift=round(current.overall_pass_rate() - baseline.overall_pass_rate(), 4),
        ci_low=low,
        ci_high=high,
        significant=sig,
        cases=cases,
    )


class GateDecision(BaseModel):
    passed: bool
    reasons: list[str]
    diff: DiffReport | None = None


def gate_decision(
    result: RunResult,
    gate: GateConfig,
    baseline: RunResult | None = None,
) -> GateDecision:
    """Evaluate CI gate rules. Exit-code semantics for `evalhive run --gate`."""
    reasons: list[str] = []
    report = None
    rate = result.overall_pass_rate()
    if rate < gate.min_pass_rate - 1e-9:
        reasons.append(f"pass_rate {rate:.2%} below min_pass_rate {gate.min_pass_rate:.2%}")
    if baseline is not None:
        report = diff_runs(baseline, result)
        if gate.max_regression is not None:
            regression = baseline.overall_pass_rate() - rate
            if regression > gate.max_regression + 1e-9:
                reasons.append(
                    f"regression {regression:.2%} exceeds max_regression {gate.max_regression:.2%} "
                    f"(drift 95% CI [{report.ci_low}, {report.ci_high}]"
                    f"{' - statistically significant' if report.significant else ''})"
                )
            if report.newly_failed:
                reasons.append("newly failed cases: "
                               + ", ".join(f"{c.provider_id}/{c.case_id}" for c in report.newly_failed))
    return GateDecision(passed=not reasons, reasons=reasons, diff=report)
