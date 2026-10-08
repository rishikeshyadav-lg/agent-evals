"""Reading a serving endpoint's reply."""

from __future__ import annotations

import pytest

pytest.importorskip("databricks.sdk")

from agent_evals.judges.databricks import _text  # noqa: E402


class _Message:
    def __init__(self, content: object) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: object) -> None:
        self.message = _Message(content)


class _Response:
    def __init__(self, *contents: object) -> None:
        self.choices = [_Choice(content) for content in contents]


def test_the_first_choice_with_text_is_the_reply() -> None:
    assert _text(_Response('{"ok": true}')) == '{"ok": true}'


def test_a_blank_first_choice_does_not_hide_a_later_one() -> None:
    assert _text(_Response("   ", "the real reply")) == "the real reply"


def test_a_response_with_no_text_reads_as_empty_rather_than_raising() -> None:
    """A criterion already treats an unreadable reply as unmeasured, which is a better verdict than
    an exception that becomes a case error and scores the agent zero."""

    assert _text(_Response()) == ""
    assert _text(_Response(None)) == ""
