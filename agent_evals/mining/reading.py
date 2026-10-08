"""Finding the question inside a trace, for the shapes worth recognising.

Separate from any particular backend because this is the part most likely to be wrong, and a test
for it should not need a warehouse client installed. It recognises the common request shapes and
returns nothing rather than a guess when it does not: a question mined wrongly becomes a case that
is wrong for as long as the dataset lives.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

QuestionReader = Callable[[Any], str | None]

# Keys a request is commonly keyed by, in the order worth trying.
_QUESTION_KEYS = ("prompt", "question", "query", "input", "text")


def question_from_request(trace: Any) -> str | None:
    """The question in a trace's request, for the shapes this module recognises.

    Returns None rather than guessing. A caller that knows its own format passes `question_of` and
    never reaches this.
    """

    request = _request_of(trace)
    if isinstance(request, str):
        return request.strip() or None
    if not isinstance(request, Mapping):
        return None
    for key in _QUESTION_KEYS:
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _last_user_message(request.get("messages"))


def _last_user_message(messages: Any) -> str | None:
    """The final user turn, which is the question a multi-turn conversation ended on."""

    if not isinstance(messages, (list, tuple)):
        return None
    for message in reversed(messages):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _request_of(trace: Any) -> Any:
    """A trace's request, whether it arrives parsed or as JSON text."""

    request = getattr(getattr(trace, "data", None), "request", None)
    if request is None:
        request = getattr(trace, "request", None)
    if isinstance(request, str):
        try:
            return json.loads(request)
        except json.JSONDecodeError:
            return request
    return request


__all__ = ["QuestionReader", "question_from_request"]
