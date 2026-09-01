"""Shared fixtures: a rag-chat run plus a gate decision."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evalhive.config.loader import load_cases, load_config
from evalhive.core.compare import gate_decision
from evalhive.core.runner import run_evaluation

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="session")
def rag_run():
    cfg, base = load_config(EXAMPLES / "rag-chat/config.yaml")
    cases = load_cases(cfg, base)
    result = asyncio.run(run_evaluation(cfg, cases, base, use_cache=False))
    return cfg, result


@pytest.fixture(scope="session")
def run_fixture(rag_run):
    cfg, result = rag_run
    return result, gate_decision(result, cfg.gate)
