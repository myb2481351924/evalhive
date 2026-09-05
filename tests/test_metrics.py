"""Unit tests for deterministic metrics."""

from __future__ import annotations

import pytest

from evalhive.config.models import AssertionConfig
from evalhive.core.metrics.deterministic import DETERMINISTIC_METRICS
from evalhive.core.providers.base import ProviderResponse


def resp(text: str, latency: float = 50.0, cost: float = 0.001) -> ProviderResponse:
    return ProviderResponse(text=text, latency_ms=latency, cost_usd=cost)


def run(name: str, value=None, threshold=None, **kw):
    a = AssertionConfig(type=name, value=value, threshold=threshold)
    return DETERMINISTIC_METRICS[name](a, None, resp(**kw))


def test_equals_and_icontains():
    assert run("equals", "Hello  World", text="hello world").passed
    assert not run("equals", "nope", text="yes").passed
    m = run("icontains", ["a", "b"], text="xa")
    assert not m.passed and m.score == 0.5


def test_regex():
    assert run("regex", r"ORDER\s+BY x LIMIT 10", text="select ORDER BY x LIMIT 10").passed
    assert not run("regex", r"ORDER BY y", text="ORDER BY x").passed
    assert not run("regex", r"([unclosed", text="whatever").passed  # bad regex fails safely


def test_json_valid_and_schema():
    assert run("json-valid", text='{"a": 1}').passed
    assert run("json-valid", text='```json\n{"a": 1}\n```').passed  # fenced
    assert not run("json-valid", text="not json").passed

    schema = {"type": "object", "required": ["a"]}
    assert run("json-schema", schema, text='{"a": 1}').passed
    m = run("json-schema", schema, text='{"b": 2}')
    assert not m.passed and "required" in m.detail


def test_latency_and_cost_thresholds():
    assert run("latency", threshold=100, text="x", latency=50).passed
    assert not run("latency", threshold=100, text="x", latency=200).passed
    assert run("cost", threshold=0.01, text="x", cost=0.001).passed
    assert not run("cost", threshold=0.01, text="x", cost=0.02).passed


def test_similarity():
    m = run("similarity", "def fib(n): return n", threshold=0.5, text="def fib(n): return n + 0")
    assert m.passed and 0.5 < m.score < 1.0


@pytest.mark.parametrize("name", sorted(DETERMINISTIC_METRICS))
def test_scores_within_bounds(name):
    m = run(name, value=0.001 if name == "cost" else (100 if name == "latency" else "x"), text="x")
    assert 0.0 <= m.score <= 1.0
