"""A judge on a Databricks model serving endpoint. Optional: `pip install "agent-evals[databricks]"`.

Text in, text out, which is the whole of `JudgeClient`. The endpoint is named, never defaulted: a
judge's identity belongs in a config a reader can see, because changing the model changes every
score it produced.

Authentication is never passed in, for the same reason as the SQL adapter. The Databricks SDK
already resolves it from the environment or `~/.databrickscfg`, and re-asking for a host and a token
would mean copying credentials that are already on the machine into a second place.

`temperature` defaults to 0. A judge is asked the same question about the same answer on every run,
and sampling would make a score move when nothing about the agent did.
"""

from __future__ import annotations

import asyncio
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from ..scoring.judging import JudgeClient


def open_databricks_judge(
    *,
    endpoint: str,
    profile: str = "",
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> JudgeClient:
    """A judge client over one serving endpoint.

    `profile` names a section of `~/.databrickscfg`; leave it empty to let the SDK resolve
    authentication the way it normally would.
    """

    if not endpoint.strip():
        raise ValueError("endpoint is required to know which model judges")
    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()

    def ask(prompt: str) -> str:
        response = client.serving_endpoints.query(
            name=endpoint,
            messages=[ChatMessage(role=ChatMessageRole.USER, content=prompt)],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _text(response)

    async def judge(prompt: str) -> str:
        return await asyncio.to_thread(ask, prompt)

    return judge


def _text(response: Any) -> str:
    """The reply's text, or "" when the endpoint returned a shape with none.

    An empty string rather than a raise: a criterion already treats an unreadable reply as
    unmeasured, and that is a better verdict than an exception that becomes a case error and scores
    the agent zero.
    """

    choices = getattr(response, "choices", None) or []
    for choice in choices:
        content = getattr(getattr(choice, "message", None), "content", None)
        if isinstance(content, str) and content.strip():
            return content
    return ""


__all__ = ["open_databricks_judge"]
