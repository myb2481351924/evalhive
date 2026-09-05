"""Pydantic models for declarative evaluation configs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AssertionConfig(BaseModel):
    """One assertion (metric) applied to a case response."""

    type: str = Field(description="Metric name, e.g. equals / icontains / llm-correctness")
    value: Any = Field(default=None, description="Expected value, regex, or JSON schema")
    threshold: float | None = Field(
        default=None, description="Numeric threshold for latency/cost/regression metrics"
    )
    provider: str | None = Field(
        default=None, description="Judge provider id for LLM-as-judge metrics"
    )
    rubric: str | None = Field(
        default=None, description="Extra judging instructions for judge metrics"
    )


class ProviderConfig(BaseModel):
    id: str
    type: Literal["openai", "mock"] = "openai"
    model: str | None = None
    base_url: str | None = Field(default=None, description="OpenAI-compatible endpoint")
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout_s: float = 60.0
    prompt_template: str | None = Field(
        default=None,
        description="Template with {prompt} and {context} placeholders; "
        "defaults to sending context as a preamble block",
    )
    # mock-only options
    responses_file: str | None = Field(
        default=None, description="JSONL of {case_id|match, response, latency_ms}"
    )
    default_response: str | None = None


class PromptVariant(BaseModel):
    """One prompt variant; the matrix becomes providers x prompts x cases when set."""

    id: str
    template: str = Field(
        description="Prompt template with a {prompt} placeholder (plus {context} and case vars)"
    )


class DatasetConfig(BaseModel):
    path: str = Field(description="JSONL file, relative to the config file")
    vars: dict[str, Any] = Field(default_factory=dict)


class DefaultsConfig(BaseModel):
    assert_: list[AssertionConfig] = Field(default_factory=list, alias="assert")

    model_config = {"populate_by_name": True}


class GateConfig(BaseModel):
    min_pass_rate: float = 1.0
    max_regression: float | None = Field(
        default=None, description="Fail if pass-rate drop vs baseline exceeds this (0..1)"
    )


class EvalConfig(BaseModel):
    description: str = ""
    providers: list[ProviderConfig] = Field(
        default_factory=list, description="Target providers evaluated in the matrix"
    )
    judge_providers: list[ProviderConfig] = Field(
        default_factory=list,
        description="LLM-judge services; available to judge metrics but NOT evaluated as targets",
    )
    prompts: list[PromptVariant] = Field(
        default_factory=list,
        description="Prompt variants: every target provider x variant x case is evaluated. "
        "Omit to use each provider's own prompt_template.",
    )
    datasets: list[DatasetConfig] = Field(default_factory=list)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    judge_provider: str | None = Field(
        default=None, description="Default judge provider id for LLM-judge metrics"
    )


class Case(BaseModel):
    """One evaluation case, loaded from a dataset JSONL."""

    id: str
    prompt: str
    context: list[str] = Field(default_factory=list)
    expected: Any = None
    vars: dict[str, Any] = Field(default_factory=dict)
    assert_: list[AssertionConfig] = Field(default_factory=list, alias="assert")

    model_config = {"populate_by_name": True}
