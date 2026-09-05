"""Simplified RAGAS-style metrics for retrieval-augmented answers.

faithfulness    -- is every claim in the answer supported by the retrieved context?
answer-relevance -- does the answer actually address the question?

Both delegate scoring to a judge provider, but with RAG-specific prompts.
"""

from __future__ import annotations

import re

from ...config.models import Case
from ..providers.base import ProviderResponse
from ..results import MetricResult
from . import MetricContext, register
from .judge import build_prompt, parse_judge


@register("faithfulness")
async def m_faithfulness(a, case: Case, response: ProviderResponse, ctx: MetricContext) -> MetricResult:
    if not case.context:
        return MetricResult(metric="faithfulness", score=0.0, passed=False,
                            detail="case has no context -- faithfulness is undefined")
    task = (
        "Break the ANSWER into individual factual claims. Count how many claims are fully "
        "supported by the REFERENCE CONTEXT. Report the count on a line 'SUPPORTED: x/y', "
        "then give SCORE = round(5 * x / y). A claim inventing facts not in the context is unsupported."
    )
    provider = ctx.resolve_judge(a)
    if provider is None:
        return MetricResult(metric="faithfulness", score=0.0, passed=False,
                            detail="no judge provider configured")
    prompt = build_prompt(task, case, response, a.rubric)
    jr = await ctx.ask(provider.config.id, prompt)
    if not jr.ok:
        return MetricResult(metric="faithfulness", score=0.0, passed=False,
                            detail=f"judge call failed: {jr.error}")
    verdict, raw = parse_judge(jr.text)
    ratio = None
    m = re.search(r"SUPPORTED:\s*(\d+)\s*/\s*(\d+)", jr.text, re.I)
    if m and int(m.group(2)) > 0:
        ratio = int(m.group(1)) / int(m.group(2))
    score = ratio if ratio is not None else (raw / 5 if raw is not None else (1.0 if verdict else 0.0))
    threshold = a.threshold if a.threshold is not None else 0.8
    return MetricResult(metric="faithfulness", score=round(min(1.0, max(0.0, score)), 4),
                        passed=score >= threshold,
                        detail=f"supported={m.group(0) if m else 'n/a'} score={score:.2f} :: {jr.text[:160]}",
                        cost_usd=jr.cost_usd, latency_ms=jr.latency_ms)


@register("answer-relevance")
async def m_answer_relevance(a, case: Case, response: ProviderResponse, ctx: MetricContext) -> MetricResult:
    task = (
        "Does the ANSWER fully address the QUESTION? Penalize partial answers, hedging, "
        "or answering a different question."
    )
    provider = ctx.resolve_judge(a)
    if provider is None:
        return MetricResult(metric="answer-relevance", score=0.0, passed=False,
                            detail="no judge provider configured")
    prompt = build_prompt(task, case, response, a.rubric)
    jr = await ctx.ask(provider.config.id, prompt)
    if not jr.ok:
        return MetricResult(metric="answer-relevance", score=0.0, passed=False,
                            detail=f"judge call failed: {jr.error}")
    verdict, raw = parse_judge(jr.text)
    if verdict is None and raw is None:
        return MetricResult(metric="answer-relevance", score=0.0, passed=False,
                            detail=f"unparseable judge output: {jr.text[:200]!r}")
    score = raw / 5 if raw is not None else (1.0 if verdict else 0.0)
    threshold = a.threshold if a.threshold is not None else 0.8
    return MetricResult(metric="answer-relevance", score=round(score, 4), passed=score >= threshold,
                        detail=f"judge score={raw} verdict={verdict} :: {jr.text[:160]}",
                        cost_usd=jr.cost_usd, latency_ms=jr.latency_ms)
