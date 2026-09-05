"""Storage round-trip: float pass-rate precision and baseline pinning."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evalhive.config.loader import load_cases, load_config
from evalhive.core.runner import run_evaluation
from evalhive.storage import Store

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def rag_result():
    cfg, base = load_config(EXAMPLES / "rag-chat/config.yaml")
    cases = load_cases(cfg, base)
    return asyncio.run(run_evaluation(cfg, cases, base, use_cache=False))


def test_pass_rate_survives_roundtrip_float(tmp_path, rag_result):
    """0.8 must come back as 0.8, not truncated to an int (Postgres-safe column)."""
    store = Store(f"sqlite:///{tmp_path / 't.sqlite3'}")
    run_id = store.save_run(rag_result, "float-precision")
    row = store.get_run_row(run_id)
    assert row.pass_rate == pytest.approx(rag_result.overall_pass_rate())
    assert store.get_run(run_id).overall_pass_rate() == pytest.approx(0.8)


def test_baseline_pinning(tmp_path, rag_result):
    store = Store(f"sqlite:///{tmp_path / 't.sqlite3'}")
    id1 = store.save_run(rag_result, "first")
    id2 = store.save_run(rag_result, "second")
    assert store.set_baseline(id2)
    assert store.get_baseline_row().id == id2
    assert store.set_baseline(id1)
    assert store.get_baseline_row().id == id1
    assert not store.set_baseline(999)
