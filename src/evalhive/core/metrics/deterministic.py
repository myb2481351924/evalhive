"""Deterministic metrics: no LLM calls, zero cost, CI-friendly."""

from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator

from ...config.models import Case
from ..providers.base import ProviderResponse
from ..results import MetricResult


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def m_equals(a, case: Case, r: ProviderResponse) -> MetricResult:
    exp = str(a.value or "")
    ok = _norm(exp) == _norm(r.text)
    return MetricResult(metric="equals", score=1.0 if ok else 0.0, passed=ok,
                        detail=f"expected={exp[:80]!r} got={r.text[:80]!r}")


def m_icontains(a, case: Case, r: ProviderResponse) -> MetricResult:
    needles = a.value if isinstance(a.value, list) else [a.value]
    text = _norm(r.text)
    missing = [str(n) for n in needles if _norm(str(n)) not in text]
    score = (len(needles) - len(missing)) / max(1, len(needles))
    return MetricResult(metric="icontains", score=round(score, 4), passed=not missing,
                        detail=f"missing={missing}" if missing else "")


def m_regex(a, case: Case, r: ProviderResponse) -> MetricResult:
    try:
        ok = re.search(str(a.value or ""), r.text) is not None
    except re.error as e:
        return MetricResult(metric="regex", score=0.0, passed=False, detail=f"bad regex: {e}")
    return MetricResult(metric="regex", score=1.0 if ok else 0.0, passed=ok,
                        detail=f"pattern={a.value!r}")


def m_json_valid(a, case: Case, r: ProviderResponse) -> MetricResult:
    try:
        json.loads(_extract_json(r.text))
        ok, detail = True, ""
    except (json.JSONDecodeError, ValueError) as e:
        ok, detail = False, f"not valid JSON: {e}"
    return MetricResult(metric="json-valid", score=1.0 if ok else 0.0, passed=ok, detail=detail)


def m_json_schema(a, case: Case, r: ProviderResponse) -> MetricResult:
    try:
        obj = json.loads(_extract_json(r.text))
    except (json.JSONDecodeError, ValueError) as e:
        return MetricResult(metric="json-schema", score=0.0, passed=False,
                            detail=f"not valid JSON: {e}")
    errors = sorted(Draft202012Validator(a.value or {}).iter_errors(obj), key=lambda e: e.path)
    if errors:
        return MetricResult(metric="json-schema", score=0.0, passed=False,
                            detail=f"{len(errors)} schema violation(s): {errors[0].message}")
    return MetricResult(metric="json-schema", score=1.0, passed=True)


def m_latency(a, case: Case, r: ProviderResponse) -> MetricResult:
    th = float(a.threshold if a.threshold is not None else a.value)
    ok = r.latency_ms <= th
    return MetricResult(metric="latency", score=1.0 if ok else 0.0, passed=ok,
                        detail=f"{r.latency_ms:.0f}ms vs threshold {th:.0f}ms")


def m_cost(a, case: Case, r: ProviderResponse) -> MetricResult:
    th = float(a.threshold if a.threshold is not None else a.value)
    ok = r.cost_usd <= th
    return MetricResult(metric="cost", score=1.0 if ok else 0.0, passed=ok,
                        detail=f"${r.cost_usd:.6f} vs threshold ${th:.6f}")


def m_similarity(a, case: Case, r: ProviderResponse) -> MetricResult:
    """Token-set Jaccard similarity vs expected, pass at threshold (default 0.8)."""
    exp = _norm(str(a.value or "")).split()
    got = _norm(r.text).split()
    inter = len(set(exp) & set(got))
    union = len(set(exp) | set(got)) or 1
    score = inter / union
    th = float(a.threshold if a.threshold is not None else 0.8)
    return MetricResult(metric="similarity", score=round(score, 4), passed=score >= th,
                        detail=f"jaccard={score:.2f} vs threshold {th}")


def _extract_json(text: str) -> str:
    """Tolerate markdown fences / surrounding prose by grabbing the outermost
    {...} or [...] block when the raw text isn't already pure JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s, e = text.find(open_c), text.rfind(close_c)
        if s != -1 and e > s:
            candidate = text[s : e + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                continue
    return text


DETERMINISTIC_METRICS = {
    "equals": m_equals,
    "icontains": m_icontains,
    "regex": m_regex,
    "json-valid": m_json_valid,
    "json-schema": m_json_schema,
    "latency": m_latency,
    "cost": m_cost,
    "similarity": m_similarity,
}
