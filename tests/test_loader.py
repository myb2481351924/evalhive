"""Tests for judge/RAG metric parsing and the config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalhive.config.loader import ConfigError, config_hash, load_cases, load_config
from evalhive.core.metrics.judge import parse_judge

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_parse_judge_variants():
    assert parse_judge("VERDICT: pass\nSCORE: 5") == (True, 5.0)
    assert parse_judge("verdict: FAIL, it hallucinates.\nSCORE: 1") == (False, 1.0)
    assert parse_judge("SCORE: 3") == (None, 3.0)
    assert parse_judge("I cannot decide") == (None, None)
    assert parse_judge("SCORE: 99") == (None, None)  # out-of-range rejected


def test_load_rag_chat_example():
    cfg, base = load_config(EXAMPLES / "rag-chat/config.yaml")
    cases = load_cases(cfg, base)
    assert [c.id for c in cases] == ["c1", "c2", "c3", "c4", "c5"]
    assert cfg.judge_provider == "judge"
    assert {p.id for p in cfg.judge_providers} == {"judge"}
    h1 = config_hash(cfg, cases)
    assert h1 == config_hash(cfg, cases)  # stable
    cases[0].expected = "mutated"
    assert config_hash(cfg, cases) != h1  # dataset change => new hash


def test_config_hash_includes_mock_fixture_content(tmp_path: Path):
    ds = tmp_path / "d.jsonl"
    ds.write_text('{"id":"a","prompt":"q"}\n', encoding="utf-8")
    fix = tmp_path / "r.jsonl"
    fix.write_text('{"case_id":"a","response":"one"}\n', encoding="utf-8")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "providers:\n  - id: m\n    type: mock\n    responses_file: r.jsonl\n"
        "datasets: [{path: d.jsonl}]\n",
        encoding="utf-8",
    )
    cfg, base = load_config(cfg_file)
    cases = load_cases(cfg, base)
    h1 = config_hash(cfg, cases, base)
    assert h1 == config_hash(cfg, cases, base)
    fix.write_text('{"case_id":"a","response":"completely different"}\n', encoding="utf-8")
    assert config_hash(cfg, cases, base) != h1  # fixture edit == input edit


def test_duplicate_case_ids_rejected(tmp_path: Path):
    ds = tmp_path / "d.jsonl"
    ds.write_text('{"id":"x","prompt":"a"}\n{"id":"x","prompt":"b"}\n', encoding="utf-8")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "providers:\n  - id: p\n    type: mock\n    default_response: ok\n"
        "datasets:\n  - path: d.jsonl\n",
        encoding="utf-8",
    )
    cfg, base = load_config(cfg_file)
    with pytest.raises(ConfigError, match="duplicate"):
        load_cases(cfg, base)


def test_unknown_judge_ref_rejected(tmp_path: Path):
    ds = tmp_path / "d.jsonl"
    ds.write_text('{"id":"x","prompt":"a","assert":[{"type":"llm-correctness","provider":"ghost"}]}\n',
                  encoding="utf-8")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "providers:\n  - id: p\n    type: mock\n    default_response: ok\ndatasets:\n  - path: d.jsonl\n",
        encoding="utf-8",
    )
    cfg, base = load_config(cfg_file)
    with pytest.raises(ConfigError, match="ghost"):
        load_cases(cfg, base)
