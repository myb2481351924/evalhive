"""Core public API: import these to embed EvalHive in your own pipeline."""

from .results import CaseEval, MetricResult, ProviderSummary, RunResult
from .runner import run_evaluation

__all__ = ["CaseEval", "MetricResult", "ProviderSummary", "RunResult", "run_evaluation"]
