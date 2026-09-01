"""Provider abstraction: everything that turns a prompt into a response."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ...config.models import Case, ProviderConfig


class ProviderResponse(BaseModel):
    text: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    raw: dict | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMProvider(ABC):
    """A provider receives fully-rendered prompts.

    The runner renders prompts from cases via render_prompt(); judge metrics
    build their own prompt strings and call complete() directly -- so every
    LLM call in the system funnels through one cacheable entry point.
    """

    def __init__(self, config: ProviderConfig):
        self.config = config

    def render_prompt(self, case: Case) -> str:
        ctx = "\n\n".join(case.context)
        if self.config.prompt_template:
            return self.config.prompt_template.format(prompt=case.prompt, context=ctx, **case.vars)
        if ctx:
            return f"Context:\n{ctx}\n\nQuestion: {case.prompt}"
        return case.prompt

    def cache_salt(self) -> str:
        """Identity of the provider *implementation*; mixed into response cache
        keys so changing model params or mock fixtures invalidates old entries."""
        return f"{self.config.model}:{self.config.temperature}"

    @abstractmethod
    async def complete(self, prompt: str, *, case_id: str | None = None) -> ProviderResponse:
        ...


def estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    """Rough USD cost estimate from public list prices (per 1M tokens)."""
    pricing = {
        "gpt-4o-mini": (0.15, 0.6),
        "gpt-4o": (2.5, 10.0),
        "gpt-4.1-mini": (0.4, 1.6),
        "claude-3-5-sonnet": (3.0, 15.0),
        "claude-3-5-haiku": (0.8, 4.0),
        "deepseek-chat": (0.27, 1.1),
        "qwen-plus": (0.8, 2.0),
    }
    rates = (0.5, 1.5)  # conservative default for unknown models
    if model:
        for prefix, r in pricing.items():
            if model.startswith(prefix):
                rates = r
                break
    return round((prompt_tokens * rates[0] + completion_tokens * rates[1]) / 1_000_000, 6)
