"""Shared builders for attribution tests."""

from __future__ import annotations

from typing import Any

from agent_evals.core.evaluation import VariantCaseResult
from agent_evals.core.prediction import PredictionResult
from agent_evals.core.steps import GenericStep, GenericTrajectory
from agent_evals.running.execution import RepeatedRun, RunRow, RunSettings


def result(
    *,
    metrics: dict[str, float] | None = None,
    details: dict[str, dict[str, Any]] | None = None,
    error: str | None = None,
    latency_ms: float | None = 1_000.0,
    cost_usd: float | None = None,
    llm_usage: dict[str, Any] | None = None,
    output: Any = None,
) -> VariantCaseResult:
    return VariantCaseResult(
        variant_id="prd",
        metrics=metrics or {},
        error=error,
        score_details=details or {},
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        llm_usage=llm_usage or {},
        output=output,
    )


def row(
    *,
    case_id: str = "c1",
    repeat: int = 0,
    tool_calls: list[dict[str, Any]] | None = None,
    answer: str | None = "an answer",
    steps_recorded: bool | None = True,
    category: str | None = None,
    **kwargs: Any,
) -> RunRow:
    return RunRow(
        case_id=case_id,
        variant_id="prd",
        repeat=repeat,
        result=result(**kwargs),
        answer=answer,
        tool_calls=tuple(tool_calls or []),
        category=category,
        steps_recorded=steps_recorded,
    )


def prediction(
    *, answer: str = "an answer", steps: list[GenericStep] | None = None, trajectory: bool = True
) -> PredictionResult:
    return PredictionResult(
        answer=answer,
        trajectory=GenericTrajectory(query="q", steps=tuple(steps or [])) if trajectory else None,
    )


def run(*rows: RunRow) -> RepeatedRun:
    return RepeatedRun(settings=RunSettings(repeats=1), rows=tuple(rows))
