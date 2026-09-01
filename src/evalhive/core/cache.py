"""File-backed response cache: same prompt + provider => same cached answer.

Caching makes reruns free and results reproducible (a rerun of an unchanged
config_hash is a full cache hit). Bump --no-cache to force fresh calls.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Awaitable, Callable

from .providers.base import ProviderResponse

Factory = Callable[[], Awaitable[ProviderResponse]]


class ResponseCache:
    def __init__(self, dir: Path | None = None):
        self.dir = dir
        self._mem: dict[str, ProviderResponse] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(provider_id: str, prompt: str) -> str:
        h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24]
        return f"{provider_id}:{h}"

    async def get_or_call(self, key: str, factory: Factory) -> ProviderResponse:
        if key in self._mem:
            self.hits += 1
            return self._mem[key]
        path = self.dir / f"{key.replace(':', '_')}.json" if self.dir else None
        if path and path.exists():
            try:
                resp = ProviderResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))
                if resp.ok:  # never cache a failed call
                    self._mem[key] = resp
                    self.hits += 1
                    return resp
            except (json.JSONDecodeError, ValueError):
                pass  # corrupted entry -> recompute
        self.misses += 1
        resp = await factory()
        if resp.ok and path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(resp.model_dump_json(), encoding="utf-8")
        self._mem[key] = resp
        return resp
