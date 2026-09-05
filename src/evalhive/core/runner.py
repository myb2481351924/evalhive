"""Evaluation runner: executes the provider x case matrix concurrently."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from ..config.loader import config_hash
from ..config.models import AssertionConfig, Case, EvalConfig
from .cache import ResponseCache
from .metrics import MetricContext, evaluate, import_llm_metrics
from .providers import build_provider
from .results import CaseEval, RunResult

import_llm_metrics()


def merge_assertions(cfg: EvalConfig, case: Case) -> list[AssertionConfig]:
    """Case-level assertions override config defaults of the same metric type."""
    by_type: dict[str, AssertionConfig] = {}
    for a in cfg.defaults.assert_:
        by_type[a.type] = a
    for a in case.assert_:
        by_type[a.type] = a
    return list(by_type.values())


async def run_evaluation(
    cfg: EvalConfig,
    cases: list[Case],
    config_dir: Path,
    *,
    concurrency: int = 5,
    use_cache: bool = True,
    cache_dir: Path | None = None,
    progress=None,
) -> RunResult:
    targets = {p.id: build_provider(p, config_dir) for p in cfg.providers}
    all_providers = dict(targets)
    for p in cfg.judge_providers:
        all_providers[p.id] = build_provider(p, config_dir)
    cache = ResponseCache((cache_dir or Path(".evalhive/cache")) if use_cache else None)
    ctx = MetricContext(all_providers, default_judge=cfg.judge_provider, cache=cache,
                        concurrency=concurrency)
    sem = asyncio.Semaphore(concurrency)

    async def one(provider_id: str, case: Case) -> CaseEval:
        provider = targets[provider_id]
        try:
            prompt = provider.render_prompt(case)
        except Exception as e:  # noqa: BLE001 - bad template/vars fail this case, not the run
            return CaseEval(
                provider_id=provider_id,
                case_id=case.id,
                error=f"prompt render failed: {type(e).__name__}: {e}",
            )
        assertions = merge_assertions(cfg, case)
        async with sem:
            response = await cache.get_or_call(
                ResponseCache.key(f"main:{provider_id}:{provider.cache_salt()}", prompt),
                lambda: provider.complete(prompt, case_id=case.id),
            )
        metrics = []
        if response.ok:
            for a in assertions:
                metrics.append(await evaluate(a, case, response, ctx))
            if not assertions:
                from .results import MetricResult

                metrics.append(MetricResult(metric="no-assert", score=1.0, passed=True,
                                            detail="no assertions defined for this case"))
        return CaseEval(
            provider_id=provider_id,
            case_id=case.id,
            prompt=prompt,
            response=response.text,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            metrics=metrics,
            error=response.error,
        )

    tasks = [one(pid, case) for pid in targets for case in cases]
    try:
        evals: list[CaseEval] = []
        for coro in asyncio.as_completed(tasks):
            evals.append(await coro)
            if progress:
                progress(len(evals), len(tasks))
    finally:
        for p in all_providers.values():
            await p.aclose()
    evals.sort(key=lambda e: (e.provider_id, e.case_id))
    return RunResult(
        config_hash=config_hash(cfg, cases, config_dir),
        description=cfg.description,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        results=evals,
    )
