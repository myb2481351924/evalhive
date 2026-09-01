"""Cache-salt and report-format tests."""

from __future__ import annotations

from pathlib import Path

from evalhive.config.loader import load_config
from evalhive.core.cache import ResponseCache
from evalhive.core.providers import build_provider
from evalhive.report import to_junit_xml, to_markdown

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


async def _mock_provider(tmp_path: Path, response_text: str = "one"):
    (tmp_path / "r.jsonl").write_text(f'{{"case_id":"a","response":"{response_text}"}}\n',
                                      encoding="utf-8")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "providers:\n  - id: m\n    type: mock\n    responses_file: r.jsonl\n"
        "datasets: [{path: x.jsonl}]\n",
        encoding="utf-8",
    )
    cfg, _ = load_config(cfg_file)
    return build_provider(cfg.providers[0], tmp_path)


async def test_cache_salt_tracks_fixture_changes(tmp_path: Path):
    p1 = await _mock_provider(tmp_path, "one")
    salt1 = p1.cache_salt()
    assert (await p1.complete("q", case_id="a")).text == "one"

    p2 = await _mock_provider(tmp_path, "two")
    assert p2.cache_salt() != salt1  # fixture edited => different salt => cache miss


async def test_response_cache_roundtrip(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache")
    calls = []

    async def factory():
        from evalhive.core.providers.base import ProviderResponse

        calls.append(1)
        return ProviderResponse(text="v1", latency_ms=1)

    r1 = await cache.get_or_call("k:1", factory)
    r2 = await cache.get_or_call("k:1", factory)
    assert r1.text == r2.text == "v1" and len(calls) == 1
    # fresh cache instance, same dir: loads from disk, no extra call
    r3 = await ResponseCache(tmp_path / "cache").get_or_call("k:1", factory)
    assert r3.text == "v1" and len(calls) == 1


def test_reports_render(run_fixture):
    result, decision = run_fixture
    xml = to_junit_xml(result)
    assert xml.startswith("<?xml") and "<testsuite" in xml
    md = to_markdown(result, decision)
    assert "Gate:" in md and "pass rate" in md
