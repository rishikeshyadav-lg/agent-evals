"""Reading real questions out of MLflow traces. Optional: `pip install "agent-evals[mlflow]"`.

MLflow records a trace per conversation, and the question is in its request. Where exactly depends on
how the agent was instrumented, which is why `question_of` exists: this module handles the search,
the window and the paging, and hands each trace to a function of yours for the one part only you can
answer.

The default reader covers the common shape -- a request holding a `prompt`, `question`, `input` or
`messages` -- and returns nothing rather than a guess when it does not recognise what it is given. A
trace it cannot read is skipped and counted, so a window that yields little says so instead of
looking empty.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import mlflow

from .reading import QuestionReader, question_from_request
from .source import MinedQuestion, TraceQuery, TraceSource


def open_mlflow(
    *,
    experiment_id: str,
    question_of: QuestionReader = question_from_request,
    filter_string: str = "",
) -> TraceSource:
    """A trace source over one MLflow experiment.

    `question_of` is the seam: give it a function that pulls the question out of your own traces and
    everything else here works unchanged.
    """

    if not experiment_id.strip():
        raise ValueError("experiment_id is required to know which traces to read")

    def search(query: TraceQuery) -> list[MinedQuestion]:
        since = datetime.now(UTC) - timedelta(days=query.since_days)
        clauses = [f"timestamp_ms > {int(since.timestamp() * 1000)}"]
        if filter_string:
            clauses.append(filter_string)
        traces = mlflow.search_traces(
            locations=[experiment_id],
            filter_string=" AND ".join(clauses),
            max_results=query.limit,
            return_type="list",
        )
        return _mined(traces, query, question_of)

    async def source(query: TraceQuery) -> list[MinedQuestion]:
        return await asyncio.to_thread(search, query)

    return source


def _mined(traces: Any, query: TraceQuery, question_of: QuestionReader) -> list[MinedQuestion]:
    mined: list[MinedQuestion] = []
    for trace in traces:
        user = _tag(trace, "mlflow.user") or _tag(trace, "user")
        if user and user in query.exclude_users:
            continue
        question = question_of(trace)
        if not question:
            continue
        mined.append(
            MinedQuestion(
                question=question,
                trace_id=str(_trace_id(trace)),
                recorded_at=_recorded_at(trace),
                metadata={"user": user} if user else {},
            )
        )
    return mined


def _trace_id(trace: Any) -> Any:
    info = getattr(trace, "info", None)
    return getattr(info, "trace_id", None) or getattr(trace, "trace_id", "")


def _tag(trace: Any, name: str) -> str:
    tags = getattr(getattr(trace, "info", None), "tags", None) or {}
    value = tags.get(name) if isinstance(tags, Mapping) else None
    return str(value) if value else ""


def _recorded_at(trace: Any) -> str:
    """When the question was asked, as an ISO string, so a dataset can order by it."""

    milliseconds = getattr(getattr(trace, "info", None), "timestamp_ms", None)
    if not isinstance(milliseconds, (int, float)):
        return ""
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat(timespec="seconds")


__all__ = ["open_mlflow"]
