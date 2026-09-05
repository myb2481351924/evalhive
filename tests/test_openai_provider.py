"""OpenAI provider tests over a fully offline httpx.MockTransport.

Covers the branches a real API throws at you: success with usage accounting,
HTTP errors, malformed JSON, missing key -- plus the pooled-client contract.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from evalhive.config.models import ProviderConfig
from evalhive.core.providers.openai_provider import OpenAIProvider

COMPLETION = {
    "id": "cmpl-1",
    "choices": [{"message": {"content": "  the answer "}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
}


def make_provider(handler) -> OpenAIProvider:
    cfg = ProviderConfig(id="p", type="openai", model="gpt-4o-mini", api_key_env="_EH_TEST_KEY")
    provider = OpenAIProvider(cfg)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("_EH_TEST_KEY", "sk-test")


def test_success_accounting(api_key):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json=COMPLETION)

    provider = make_provider(handler)
    resp = asyncio.run(provider.complete("hello"))
    assert resp.ok and resp.text == "  the answer "
    assert (resp.prompt_tokens, resp.completion_tokens) == (100, 50)
    assert resp.cost_usd > 0  # gpt-4o-mini rates applied
    assert seen["auth"] == "Bearer sk-test"
    assert seen["payload"]["model"] == "gpt-4o-mini"
    assert seen["payload"]["messages"] == [{"role": "user", "content": "hello"}]
    asyncio.run(provider.aclose())


def test_http_error_surfaces(api_key):
    provider = make_provider(lambda req: httpx.Response(429, json={"error": "rate limited"}))
    resp = asyncio.run(provider.complete("hi"))
    assert not resp.ok and "429" in (resp.error or "")


def test_malformed_json_surfaces(api_key):
    provider = make_provider(lambda req: httpx.Response(200, content=b"not json{"))
    resp = asyncio.run(provider.complete("hi"))
    assert not resp.ok and resp.error  # JSONDecodeError path, no crash


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("_EH_TEST_KEY", raising=False)
    provider = make_provider(lambda req: httpx.Response(200, json=COMPLETION))
    resp = asyncio.run(provider.complete("hi"))
    assert not resp.ok and "_EH_TEST_KEY" in (resp.error or "")


def test_client_is_pooled_and_closed(api_key):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=COMPLETION)

    provider = make_provider(handler)
    asyncio.run(provider.complete("a"))
    client_after_first = provider._client
    asyncio.run(provider.complete("b"))
    assert provider._client is client_after_first  # same pooled client, no re-handshake
    assert len(calls) == 2
    asyncio.run(provider.aclose())
    assert provider._client is None
