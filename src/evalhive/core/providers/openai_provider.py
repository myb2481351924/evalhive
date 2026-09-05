"""OpenAI-compatible chat-completions provider (works with any /v1 base_url)."""

from __future__ import annotations

import os
import time

import httpx

from .base import LLMProvider, ProviderResponse, estimate_cost


class OpenAIProvider(LLMProvider):
    """One pooled httpx client per provider instance (reused across the whole
    run) instead of a fresh TLS handshake per call."""

    def __init__(self, config):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_s)
        return self._client

    async def complete(self, prompt: str, *, case_id: str | None = None) -> ProviderResponse:
        cfg = self.config
        api_key = os.environ.get(cfg.api_key_env, "")
        if not api_key:
            return ProviderResponse(
                error=f"env var {cfg.api_key_env} is not set for provider {cfg.id!r}"
            )
        base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        payload = {
            "model": cfg.model or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        t0 = time.perf_counter()
        try:
            r = await self._get_client().post(
                f"{base}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001 - surface any transport/API error
            return ProviderResponse(error=f"{type(e).__name__}: {e}")
        latency_ms = (time.perf_counter() - t0) * 1000
        usage = data.get("usage") or {}
        pt, ct = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        choices = data.get("choices") or [{}]
        text = choices[0].get("message", {}).get("content", "") or ""
        return ProviderResponse(
            text=text,
            latency_ms=round(latency_ms, 1),
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=estimate_cost(cfg.model, pt, ct),
            raw={"id": data.get("id")},
        )

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
