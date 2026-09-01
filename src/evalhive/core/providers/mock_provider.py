"""Mock provider: recorded or canned responses for offline, deterministic runs.

This is what makes the whole pipeline (and the CI gate) demonstrable without
any API key -- and keeps LLM-judge metrics usable offline.

Response resolution order:
1. exact ``case_id`` match in the responses file
2. substring ``match`` in the prompt (first hit wins)
3. ``default_response`` from the config
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .base import LLMProvider, ProviderResponse, estimate_cost


class MockProvider(LLMProvider):
    def __init__(self, config, base_dir: Path | None = None):
        super().__init__(config)
        self._entries: list[dict] = []
        if config.responses_file:
            p = Path(config.responses_file)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            if not p.exists():
                raise FileNotFoundError(f"mock responses file not found: {p}")
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._entries.append(json.loads(line))

    async def complete(self, prompt: str, *, case_id: str | None = None) -> ProviderResponse:
        entry = self._lookup(case_id, prompt)
        if entry is None:
            if self.config.default_response is None:
                return ProviderResponse(error=f"no mock response for case {case_id or prompt[:40]!r}")
            entry = {"response": self.config.default_response}
        text = str(entry.get("response", ""))
        latency = float(entry.get("latency_ms", 10))
        time.sleep(latency / 1000)  # simulate wall time so latency metrics behave
        pt = max(1, len(prompt) // 4)
        ct = max(1, len(text) // 4)
        return ProviderResponse(
            text=text,
            latency_ms=latency,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=estimate_cost(self.config.model, pt, ct),
        )

    def _lookup(self, case_id: str | None, prompt: str) -> dict | None:
        if case_id:
            for e in self._entries:
                if e.get("case_id") == case_id:
                    return e
        for e in self._entries:
            needle = e.get("match")
            if needle and str(needle) in prompt:
                return e
        return None
