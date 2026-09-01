"""Report formats: JUnit XML (CI artifacts), Markdown (PR comments), HTML (later)."""

from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape

from ..core.compare import GateDecision
from ..core.results import RunResult


def to_junit_xml(result: RunResult) -> str:
    cases = []
    for e in result.results:
        body = [f'  <testcase classname="evalhive.{escape(e.provider_id)}" '
                f'name="{escape(e.case_id)}" time="{e.latency_ms / 1000:.3f}">']
        if e.error:
            body.append(f'    <error message="{escape(e.error[:500])}" />')
        for m in e.metrics:
            if not m.passed:
                body.append(f'    <failure message="{escape(m.metric)}: '
                            f'{escape(m.detail[:500])}" />')
        body.append("  </testcase>")
        cases.append("\n".join(body))
    summary = f"EvalHive run {result.config_hash}"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="{escape(summary)}" tests="{len(result.results)}" '
        f'failures="{sum(1 for e in result.results if not e.passed and not e.error)}" '
        f'errors="{sum(1 for e in result.results if e.error)}">\n'
        + "\n".join(cases)
        + "\n</testsuite>\n"
    )


def to_markdown(result: RunResult, decision: GateDecision | None = None) -> str:
    """PR-comment friendly summary; gate verdict first."""
    lines = [f"### EvalHive — {result.description or result.config_hash}"]
    if decision is not None:
        lines.append(f"**Gate: {'PASSED ✅' if decision.passed else 'FAILED ❌'}**")
        for r in decision.reasons:
            lines.append(f"- ⚠️ {r}")
        if decision.diff:
            d = decision.diff
            sig = "significant" if d.significant else "not significant"
            lines.append(
                f"- Drift vs baseline: **{d.drift:+.2%}** (95% CI "
                f"[{d.ci_low:+.2%}, {d.ci_high:+.2%}], {sig})"
            )
            for c in d.newly_failed:
                lines.append(f"- ❌ newly failed: `{c.provider_id}/{c.case_id}`")
    lines += [
        "",
        "| provider | cases | pass | fail | err | pass rate | avg latency | cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pid, s in sorted(result.summary().items()):
        lines.append(
            f"| {pid} | {s.total} | {s.passed} | {s.failed} | {s.errored} | "
            f"{s.pass_rate:.1%} | {s.avg_latency_ms:.0f}ms | ${s.total_cost_usd:.4f} |"
        )
    fails = [e for e in result.results if not e.passed]
    if fails:
        lines += ["", "<details><summary>Failed cases</summary>", ""]
        for e in fails[:50]:
            if e.error:
                lines.append(f"- `{e.provider_id}/{e.case_id}` — error: {e.error[:200]}")
            else:
                bad = ", ".join(f"{m.metric}={m.score:.2f}" for m in e.metrics if not m.passed)
                lines.append(f"- `{e.provider_id}/{e.case_id}` — {bad}")
        lines += ["", "</details>"]
    lines.append(f"\n<sub>config_hash `{result.config_hash}` · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}</sub>")
    return "\n".join(lines)
