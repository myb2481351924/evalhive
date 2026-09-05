"""Result types shared by metrics, runner, storage and reports."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class MetricResult(BaseModel):
    metric: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    detail: str = ""
    cost_usd: float = 0.0  # LLM-judge call cost; deterministic metrics stay 0
    latency_ms: float = 0.0


class CaseEval(BaseModel):
    provider_id: str
    prompt_id: str = "default"  # which prompt variant produced this answer
    case_id: str
    prompt: str = ""  # empty when prompt rendering itself failed
    response: str = ""
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    metrics: list[MetricResult] = Field(default_factory=list)
    error: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return self.error is None and all(m.passed for m in self.metrics)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def judge_cost_usd(self) -> float:
        return round(sum(m.cost_usd for m in self.metrics), 6)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_cost_usd(self) -> float:
        return round(self.cost_usd + self.judge_cost_usd, 6)


class ProviderSummary(BaseModel):
    provider_id: str
    total: int
    passed: int
    failed: int
    errored: int
    pass_rate: float
    avg_latency_ms: float
    total_cost_usd: float
    avg_score: float


class RunResult(BaseModel):
    config_hash: str
    description: str = ""
    created_at: str = ""
    results: list[CaseEval] = Field(default_factory=list)

    def by_provider(self) -> dict[str, list[CaseEval]]:
        """Group by provider, splitting into one bucket per prompt variant
        ("provider" when no variants are used, "provider/variant" otherwise)."""
        out: dict[str, list[CaseEval]] = {}
        for r in self.results:
            key = r.provider_id if r.prompt_id == "default" else f"{r.provider_id}/{r.prompt_id}"
            out.setdefault(key, []).append(r)
        return out

    def summary(self) -> dict[str, ProviderSummary]:
        summaries = {}
        for pid, evals in self.by_provider().items():
            total = len(evals)
            passed = sum(1 for e in evals if e.passed)
            errored = sum(1 for e in evals if e.error)
            failed = total - passed - errored
            scores = [m.score for e in evals for m in e.metrics]
            summaries[pid] = ProviderSummary(
                provider_id=pid,
                total=total,
                passed=passed,
                failed=failed,
                errored=errored,
                pass_rate=round(passed / total, 4) if total else 0.0,
                avg_latency_ms=round(sum(e.latency_ms for e in evals) / total, 1) if total else 0.0,
                total_cost_usd=round(sum(e.total_cost_usd for e in evals), 6),
                avg_score=round(sum(scores) / len(scores), 4) if scores else 0.0,
            )
        return summaries

    def overall_pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for e in self.results if e.passed) / len(self.results)
