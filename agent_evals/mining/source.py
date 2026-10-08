"""What this library needs from your traces: give me the questions people actually asked.

One alias and two small shapes, because that is the whole contract. Reading a trace and finding the
question inside it needs to know that agent's trace format, and this package has no way to know it.
Guessing would be the same mistake it refuses to make elsewhere, so the knowledge stays with you and
the seam stays this narrow.

A source returns questions and nothing else. Not answers, not tool calls, not a verdict: an answer
recorded months ago was produced against data that has since moved, so it cannot be compared with a
query run today. What survives the passage of time is the question.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


class SourceNotInstalled(ImportError):
    """A named source exists but its client library does not."""


@dataclass(frozen=True, slots=True)
class TraceQuery:
    """Which traces to look at: how far back, how many, and whose.

    `since_days` rather than a date range because the question a person asks is "the last three
    months", and a window that moves with today is what a recurring run wants.
    """

    since_days: int = 90
    limit: int = 150
    exclude_users: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.since_days < 1:
            raise ValueError("since_days must be at least 1")
        if self.limit < 1:
            raise ValueError("limit must be at least 1")


@dataclass(frozen=True, slots=True)
class MinedQuestion:
    """One real question, and enough about it to find the conversation it came from.

    `trace_id` is the only identifier kept. It points back at the full conversation for anyone with
    access, while artifacts built from this carry no customer text they do not need.
    """

    question: str
    trace_id: str
    recorded_at: str = ""
    category: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("a mined question cannot be blank")
        if not self.trace_id.strip():
            raise ValueError("a mined question must say which trace it came from")


TraceSource = Callable[[TraceQuery], Awaitable[list[MinedQuestion]]]
"""Return the real questions asked in the window the query describes.

Async because reading traces is network-bound, and a window of three months is many calls. A source
over a blocking client wraps it in `asyncio.to_thread` rather than making callers care.
"""


__all__ = ["MinedQuestion", "SourceNotInstalled", "TraceQuery", "TraceSource"]
