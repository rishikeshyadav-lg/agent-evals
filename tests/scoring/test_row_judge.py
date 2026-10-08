"""Asking a model which rows of a breakdown an answer stated."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent_evals.scoring.figure_judge import JudgeRows

FIELDS = {"impressions": "impressions", "spend": "spend"}
TRUTH = {
    "2026-08-31": {"impressions": 152_867.0, "spend": 1_956.70},
    "2026-09-07": {"impressions": 73_633.0, "spend": 1_417.92},
}
ANSWER = "| 2026-08-31 | 152,867 | $1,956.70 |\n| 2026-09-07 | 73,633 | $1,417.92 |"


def _read(reply: str, answer: str = ANSWER) -> dict:
    return dict(asyncio.run(JudgeRows(client=lambda prompt: reply, dimension="week")(answer, FIELDS, TRUTH)))


def test_every_stated_row_comes_back_keyed_by_its_label() -> None:
    reply = json.dumps(
        {
            "2026-08-31": {"impressions": 152867, "spend": 1956.70},
            "2026-09-07": {"impressions": 73633, "spend": 1417.92},
        }
    )

    assert _read(reply)["2026-08-31"]["impressions"] == pytest.approx(152_867.0)


def test_a_row_the_answer_omitted_is_absent_rather_than_zero() -> None:
    """Absent lowers coverage. Zero would read as the agent reporting no impressions that week."""

    reply = json.dumps({"2026-08-31": {"impressions": 152867, "spend": 1956.70}})

    assert "2026-09-07" not in _read(reply)


def test_a_row_with_no_readable_figure_is_not_a_stated_row() -> None:
    reply = json.dumps({"2026-08-31": {"impressions": None, "spend": None}})

    assert _read(reply) == {}


def test_the_judge_can_report_a_figure_that_disagrees_with_the_truth() -> None:
    """It reads the answer; it does not confirm the table. A reader that only echoed the true values
    would pass every answer, which is worse than no check at all."""

    reply = json.dumps({"2026-08-31": {"impressions": 999.0, "spend": 1956.70}})

    assert _read(reply)["2026-08-31"]["impressions"] == pytest.approx(999.0)


def test_a_key_the_truth_does_not_contain_is_ignored() -> None:
    """The scorer reports invented rows from its own comparison. A judge inventing keys here would
    put figures against weeks that were never queried."""

    reply = json.dumps({"2026-10-05": {"impressions": 1.0, "spend": 1.0}})

    assert _read(reply) == {}


def test_an_unreadable_reply_raises_rather_than_reporting_no_rows() -> None:
    """No rows would read as "the answer gave no breakdown", a verdict about the agent. The judge
    having malfunctioned is a verdict about the judge."""

    with pytest.raises(ValueError, match="could not be read"):
        _read("I could not tell")


def test_an_empty_answer_needs_no_model_call() -> None:
    def never(prompt: str) -> str:
        raise AssertionError("the judge should not be called for an empty answer")

    assert asyncio.run(JudgeRows(client=never)("  ", FIELDS, TRUTH)) == {}


def test_the_prompt_names_the_dimension_and_carries_the_true_rows() -> None:
    seen: list[str] = []

    def capture(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"2026-08-31": {"impressions": 152867, "spend": 1956.70}})

    asyncio.run(JudgeRows(client=capture, dimension="week")(ANSWER, FIELDS, TRUTH))

    assert "week" in seen[0]
    assert "152867.0" in seen[0]
    assert "2026-09-07" in seen[0]
