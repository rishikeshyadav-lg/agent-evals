"""Asking a model which figure an answer stated, instead of parsing for it.

Measured on three real answers the parser read nine of twelve figures correctly: in a document with
a totals table, a weekly breakdown and six paragraphs, the figure nearest a metric's name is as
often a weekly detail as the campaign total.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agent_evals.scoring.figure_judge import JudgeClaims

FIELDS = {"spend": "spend", "clicks": "clicks"}
TRUTH = {"spend": 10_222.57, "clicks": 173.0}
ANSWER = "| Clicks | 173 |\nClicks peaked in Week 1 (132 clicks)."


def _claims(reply: str, answer: str = ANSWER) -> dict:
    return dict(asyncio.run(JudgeClaims(client=lambda prompt: reply)(answer, FIELDS, TRUTH)))


def test_a_judged_claim_is_returned_as_a_number() -> None:
    reply = json.dumps({"spend": {"stated": True, "value": 10222.57}, "clicks": {"stated": True, "value": 173}})

    assert _claims(reply) == {"spend": pytest.approx(10_222.57), "clicks": pytest.approx(173.0)}


def test_a_metric_the_answer_did_not_state_is_absent() -> None:
    """Absent means "not stated", which the scorer reports as a gap rather than as a wrong figure."""

    reply = json.dumps({"spend": {"stated": False, "value": None}, "clicks": {"stated": True, "value": 173}})

    assert "spend" not in _claims(reply)


def test_the_judge_can_disagree_with_the_truth_it_was_given() -> None:
    """It is asked to verify, not to agree. A judge that only ever echoes the true value would pass
    every answer, which is worse than no check at all."""

    reply = json.dumps({"spend": {"stated": True, "value": 99.0}, "clicks": {"stated": True, "value": 173}})

    assert _claims(reply)["spend"] == pytest.approx(99.0)


def test_stated_without_a_number_is_not_a_claim() -> None:
    """A judge saying "yes" with no figure has not said what was stated, and counting that as
    agreement would let it wave figures through unseen."""

    reply = json.dumps({"spend": {"stated": True, "value": None}, "clicks": {"stated": True, "value": 173}})

    assert "spend" not in _claims(reply)


def test_json_wrapped_in_prose_is_still_read() -> None:
    reply = 'Here is the comparison: {"clicks": {"stated": true, "value": 173}}'

    assert _claims(reply)["clicks"] == pytest.approx(173.0)


def test_an_unreadable_reply_raises_rather_than_reporting_nothing() -> None:
    """Returning no claims would read as "the answer stated no figures", which is a verdict about
    the agent. The judge having malfunctioned is a verdict about the judge."""

    with pytest.raises(ValueError, match="could not be read"):
        _claims("I could not tell")


def test_an_unreachable_judge_raises() -> None:
    def down(prompt: str) -> str:
        raise RuntimeError("rate limited")

    with pytest.raises(RuntimeError):
        asyncio.run(JudgeClaims(client=down)(ANSWER, FIELDS, TRUTH))


def test_an_empty_answer_needs_no_model_call() -> None:
    def never(prompt: str) -> str:
        raise AssertionError("the judge should not be called for an empty answer")

    assert asyncio.run(JudgeClaims(client=never)("   ", FIELDS, TRUTH)) == {}


def test_the_prompt_carries_the_true_values_to_verify_against() -> None:
    """Verification, not extraction: "the table says 173, does the answer state it?" has a right
    answer that can be checked later. "What did it state?" invites a number to be invented."""

    seen: list[str] = []

    def capture(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"clicks": {"stated": True, "value": 173}})

    asyncio.run(JudgeClaims(client=capture)(ANSWER, FIELDS, TRUTH))

    assert "173" in seen[0]
    assert "10222.57" in seen[0]
