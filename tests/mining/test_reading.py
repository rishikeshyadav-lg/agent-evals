"""Finding the question inside a trace, for the shapes the default reader recognises.

No MLflow needed: the reader takes a trace-like object, which is the seam that makes this testable.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_evals.mining import question_from_request


def _trace(request: object) -> SimpleNamespace:
    return SimpleNamespace(data=SimpleNamespace(request=request))


def test_a_request_keyed_by_prompt_is_read() -> None:
    assert question_from_request(_trace({"prompt": "how did it do?"})) == "how did it do?"


def test_a_request_that_is_json_text_is_parsed() -> None:
    """MLflow hands the request back as a string often enough that guessing wrong costs a whole run."""

    assert question_from_request(_trace('{"question": "what is the CTR?"}')) == "what is the CTR?"


def test_the_last_user_turn_is_the_question_in_a_conversation() -> None:
    """A multi-turn trace ends on what was actually being asked."""

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "how did campaign 109778 do?"},
    ]

    assert question_from_request(_trace({"messages": messages})) == "how did campaign 109778 do?"


def test_an_unrecognised_shape_returns_nothing_rather_than_a_guess() -> None:
    """The whole reason `question_of` exists: a wrong question mined here is a wrong case forever."""

    assert question_from_request(_trace({"payload": {"nested": "somewhere"}})) is None


def test_a_blank_question_is_not_a_question() -> None:
    assert question_from_request(_trace({"prompt": "   "})) is None
