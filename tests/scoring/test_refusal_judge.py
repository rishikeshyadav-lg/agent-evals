"""Asking a model whether an answer declined, and whether it stated a limitation."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent_evals import EvaluationCase
from agent_evals.scoring.figure_judge import JudgeDataGap, JudgeRefusal


class _Output:
    def __init__(self, answer: str) -> None:
        self.answer = answer


CASE = EvaluationCase("q", {"prompt": "list the top 30 apps"}, expected={})


def _refusal(reply: str, answer: str = "There is no app dimension.") -> bool:
    return asyncio.run(JudgeRefusal(client=lambda prompt: reply)(CASE, _Output(answer)))


def test_a_declining_answer_is_reported_as_declined() -> None:
    assert _refusal(json.dumps({"declined": True, "why": "no app dimension"})) is True


def test_an_answering_answer_is_not_declined() -> None:
    assert _refusal(json.dumps({"declined": False, "why": ""})) is False


def test_an_empty_answer_needs_no_model_call() -> None:
    def never(prompt: str) -> str:
        raise AssertionError("the judge should not be called for an empty answer")

    assert asyncio.run(JudgeRefusal(client=never)(CASE, _Output("  "))) is False


def test_the_prompt_carries_the_question_so_declining_can_be_judged_against_it() -> None:
    """Whether an answer declined depends on what was asked: supplying placement figures is an
    answer to one question and a refusal of another."""

    seen: list[str] = []

    def capture(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"declined": True, "why": ""})

    asyncio.run(JudgeRefusal(client=capture)(CASE, _Output("no app data")))

    assert "top 30 apps" in seen[0]


def test_an_unreadable_reply_raises_rather_than_reporting_no_refusal() -> None:
    """Reporting False would score the answer as having answered, which on these cases is the
    fabrication verdict. The caller turns a raise into Unmeasured instead."""

    with pytest.raises(ValueError, match="could not be read"):
        _refusal("I'm not sure")


def test_a_reply_without_a_boolean_raises() -> None:
    with pytest.raises(ValueError, match="true or false"):
        _refusal(json.dumps({"declined": "maybe"}))


def _gap(reply: str, gap: str = "reach is unavailable") -> bool:
    return asyncio.run(JudgeDataGap(client=lambda prompt: reply)(CASE, _Output("reach is not available here"), gap))


def test_a_stated_limitation_is_reported_as_stated() -> None:
    assert _gap(json.dumps({"stated": True, "why": "reach is not available"})) is True


def test_an_unstated_limitation_is_reported_as_absent() -> None:
    assert _gap(json.dumps({"stated": False, "why": ""})) is False


def test_an_empty_gap_needs_no_model_call() -> None:
    def never(prompt: str) -> str:
        raise AssertionError("the judge should not be called with no limitation to look for")

    assert asyncio.run(JudgeDataGap(client=never)(CASE, _Output("anything"), "  ")) is False


def test_an_unreadable_gap_reply_raises() -> None:
    with pytest.raises(ValueError, match="could not be read"):
        _gap("hard to say")


def test_the_gap_prompt_carries_the_limitation_being_looked_for() -> None:
    seen: list[str] = []

    def capture(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"stated": True})

    asyncio.run(JudgeDataGap(client=capture)(CASE, _Output("reach is not available"), "reach is unavailable"))

    assert "reach is unavailable" in seen[0]
