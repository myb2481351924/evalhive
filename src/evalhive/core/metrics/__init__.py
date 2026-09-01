"""Metric registry and dispatch.

Deterministic metrics live in deterministic.py; LLM-based metrics (judge, RAG)
register into LLM_METRICS from judge.py / rag.py.
"""

from __future__ import annotations

import hashlib

from ...config.models import AssertionConfig, Case
from ..cache import ResponseCache
from ..providers.base import LLMProvider, ProviderResponse
from ..results import MetricResult
from .deterministic import DETERMINISTIC_METRICS

LLM_METRICS: dict = {}


def register(name: str):
    def deco(fn):
        LLM_METRICS[name] = fn
        return fn

    return deco


class MetricContext:
    """Shared services a metric may need: providers, default judge, cache."""

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        default_judge: str | None = None,
        cache: ResponseCache | None = None,
    ):
        self.providers = providers
        self.default_judge = default_judge
        self.cache = cache or ResponseCache()

    def resolve_judge(self, assertion: AssertionConfig) -> LLMProvider | None:
        pid = assertion.provider or self.default_judge
        if pid is None:
            return None
        return self.providers.get(pid)

    async def ask(self, provider_id: str, prompt: str) -> ProviderResponse:
        """One cached entry point for every LLM call outside the main matrix."""
        provider = self.providers.get(provider_id)
        if provider is None:
            return ProviderResponse(error=f"provider {provider_id!r} is not declared in config")
        key = f"aux:{ResponseCache.key(provider_id, prompt)}"
        return await self.cache.get_or_call(key, lambda: provider.complete(prompt))


def metric_names() -> set[str]:
    return set(DETERMINISTIC_METRICS) | set(LLM_METRICS)


def _failed(metric: str, detail: str) -> MetricResult:
    return MetricResult(metric=metric, score=0.0, passed=False, detail=detail)


async def evaluate(
    assertion: AssertionConfig,
    case: Case,
    response: ProviderResponse,
    ctx: MetricContext,
) -> MetricResult:
    fn = DETERMINISTIC_METRICS.get(assertion.type) or LLM_METRICS.get(assertion.type)
    if fn is None:
        return _failed(assertion.type, f"unknown metric {assertion.type!r}")
    try:
        if assertion.type in DETERMINISTIC_METRICS:
            return fn(assertion, case, response)
        return await fn(assertion, case, response, ctx)
    except Exception as e:  # noqa: BLE001 - a broken metric must not kill the run
        return _failed(assertion.type, f"metric error: {type(e).__name__}: {e}")


def import_llm_metrics() -> None:
    """Populate LLM_METRICS by importing the judge/rag modules."""
    from . import judge, rag  # noqa: F401
