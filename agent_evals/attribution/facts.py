"""What attribution is allowed to read about one run, and what it could not see.

A cause must be decided the same way whether the run is being watched or read back out of a JSONL a
week later. So every rule reads `RunFacts` and nothing else, and `RunFacts` is built twice: from a
recorded `RunRow`, and from a live `VariantCaseResult` that still holds the `PredictionResult`.

Every field a recorded row cannot carry is three-valued. The honest answer to "did the agent call no
tools" on a row that never recorded a trajectory is "nobody knows" — `_tool_calls` returns an empty
list both for a run with no steps and a run with no trajectory at all. Reading that silence as
"none" is the one move that would let this blame an agent for the runner's own shape.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..core.evaluation import VariantCaseResult
from ..core.prediction import PredictionResult
from ..running.execution import RunRow

EmptyResult = Callable[[Any], bool | None]
"""Whether one tool observation says it carried no rows, or None when it does not say."""


def row_count_of(observation: Any) -> int | None:
    """The row count a tool observation declares, or None when it declares none."""

    if not isinstance(observation, Mapping):
        return None
    for key in ("row_count", "rowCount", "rows_returned"):
        value = observation.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


def declared_empty(observation: Any) -> bool | None:
    """The default `EmptyResult`: a declared row count of zero, or an observation that is an empty list.

    Narrow on purpose. An observation with no row count is silence, not zero, and a mapping with
    keys this library does not understand is not evidence of anything. A project that knows its own
    tool envelopes passes its own reader.
    """

    count = row_count_of(observation)
    if count is not None:
        return count == 0
    if isinstance(observation, (list, tuple)):
        return len(observation) == 0
    return None


@dataclass(frozen=True, slots=True)
class ToolCallFact:
    """One tool call as attribution reads it.

    `error` is None on a recorded row, which keeps only a status: `_tool_calls` drops `step.error`'s
    message and `step.failure`'s mapping, so a cause read back from a file can name the tool and the
    index but not say what went wrong inside it.
    """

    index: int
    tool: str
    errored: bool
    row_count: int | None = None
    empty: bool | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunFacts:
    """One run, reduced to what a cause may be read from.

    `calls_known` is True when the record can tell what the agent fetched, False when the runner
    returned no trajectory, and None when the record predates the field: three states because "the
    agent fetched nothing" and "nobody recorded what it fetched" have different fixes and only one
    of them is the agent's fault.
    """

    case_id: str
    variant_id: str
    repeat: int
    run_error: str | None
    answer: str | None
    calls: Sequence[ToolCallFact]
    calls_known: bool | None
    metrics: Mapping[str, float]
    score_details: Mapping[str, Mapping[str, Any]]
    category: str | None = None
    pattern_key: str | None = None
    set_name: str | None = None
    llm_usage: Mapping[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None
    cost_usd: float | None = None

    def metric(self, *names: str) -> float | None:
        """The first of these metric names the run reported, or None.

        Several names because the same criterion lands under two keys depending on how it was wired:
        a rubric criterion is reported as `accuracy.figures`, while `SqlBreakdown` cannot be a rubric
        criterion at all — it returns two scores and `_criterion_outcome` demands exactly one — so
        its scores arrive bare, as `breakdown.rows`.
        """

        for name in names:
            value = self.metrics.get(name)
            if value is not None:
                return float(value)
        return None

    def detail(self, *names: str) -> Mapping[str, Any]:
        """The score detail under the first of these names that has one, or an empty mapping."""

        for name in names:
            found = self.score_details.get(name)
            if isinstance(found, Mapping) and found:
                return found
        return {}

    def empty_calls(self) -> tuple[ToolCallFact, ...]:
        """The calls that said they carried no rows. A call that did not say is not in here."""

        return tuple(call for call in self.calls if call.empty)


def _facts(
    *,
    case_id: str,
    result: VariantCaseResult,
    repeat: int,
    calls: Sequence[ToolCallFact],
    calls_known: bool | None,
    answer: str | None,
    category: str | None,
    pattern_key: str | None,
    set_name: str | None,
) -> RunFacts:
    return RunFacts(
        case_id=case_id,
        variant_id=result.variant_id,
        repeat=repeat,
        run_error=result.error,
        answer=answer,
        calls=tuple(calls),
        calls_known=calls_known,
        metrics={name: float(value) for name, value in result.metrics.items()},
        score_details={name: dict(detail) for name, detail in result.score_details.items()},
        category=category,
        pattern_key=pattern_key,
        set_name=set_name,
        llm_usage=dict(result.llm_usage),
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
    )


def facts_of_row(row: RunRow, *, empty_result: EmptyResult = declared_empty) -> RunFacts:
    """Read a recorded row.

    `calls_known` comes from `row.steps_recorded`, which rows written before that field lack, so a
    cause needing it stays unattributable on an old file rather than being guessed.
    """

    calls = [
        ToolCallFact(
            index=index,
            tool=str(call.get("tool", "")),
            errored=str(call.get("status", "")) == "error",
            row_count=row_count_of(call.get("result")),
            empty=empty_result(call.get("result")),
        )
        for index, call in enumerate(row.tool_calls)
    ]
    return _facts(
        case_id=row.case_id,
        result=row.result,
        repeat=row.repeat,
        calls=calls,
        calls_known=row.steps_recorded if row.steps_recorded is not None else (True if calls else None),
        answer=row.answer,
        category=row.category,
        pattern_key=row.pattern_key,
        set_name=row.set_name,
    )


def facts_of_result(
    case_id: str,
    result: VariantCaseResult,
    *,
    repeat: int = 0,
    empty_result: EmptyResult = declared_empty,
    category: str | None = None,
    pattern_key: str | None = None,
    set_name: str | None = None,
) -> RunFacts:
    """Read a live result, whose output still holds the trajectory and each step's error message."""

    output = result.output
    if not isinstance(output, PredictionResult):
        # Not a prediction, so nothing about its tool calls is known. False would say the agent
        # fetched nothing, which is a claim about the agent made from the shape of the runner.
        return _facts(
            case_id=case_id,
            result=result,
            repeat=repeat,
            calls=(),
            calls_known=None,
            answer=None,
            category=category,
            pattern_key=pattern_key,
            set_name=set_name,
        )
    steps = output.trajectory.steps if output.trajectory is not None else ()
    calls = [
        ToolCallFact(
            index=index,
            tool=step.tool,
            errored=step.error is not None or step.failure is not None,
            row_count=row_count_of(step.observation),
            empty=empty_result(step.observation),
            error=step.error if step.error is not None else (str(step.failure) if step.failure else None),
        )
        for index, step in enumerate(steps)
    ]
    return _facts(
        case_id=case_id,
        result=result,
        repeat=repeat,
        calls=calls,
        calls_known=output.trajectory is not None,
        answer=output.answer,
        category=category,
        pattern_key=pattern_key,
        set_name=set_name,
    )


__all__ = [
    "EmptyResult",
    "RunFacts",
    "ToolCallFact",
    "declared_empty",
    "facts_of_result",
    "facts_of_row",
    "row_count_of",
]
