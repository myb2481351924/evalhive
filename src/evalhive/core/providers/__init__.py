"""Provider factory."""

from __future__ import annotations

from pathlib import Path

from ...config.models import ProviderConfig
from .base import LLMProvider, ProviderResponse, estimate_cost
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider

__all__ = ["LLMProvider", "ProviderResponse", "build_provider", "estimate_cost"]


def build_provider(cfg: ProviderConfig, base_dir: Path) -> LLMProvider:
    if cfg.type == "mock":
        return MockProvider(cfg, base_dir=base_dir)
    return OpenAIProvider(cfg)
