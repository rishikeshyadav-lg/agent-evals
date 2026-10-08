"""Questions whose correct answer is "that cannot be answered from this data".

Of 50 hand-reviewed rubrics for one agent's real traffic, 10 accept a refusal. Scored the ordinary
way those cases invert: the reference returns campaign totals, the answer correctly says app-level
data does not exist, and the agent is marked wrong for being right.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_evals import EvaluationCase, PredictionResult
from agent_evals.core.prediction import Unmeasured
from agent_evals.scoring.refusal import AcceptedRefusal, WhenNotRefused

ACCEPTED = "It is acceptable to say the delivery dataset has no app dimension."


def _case(accepted: str | None = ACCEPTED) -> EvaluationCase:
    expected: dict[str, Any] = {} if accepted is None else {"acceptable_non_answer": accepted}
    return EvaluationCase("q", {"prompt": "list the top 30 apps by impressions"}, expected=expected)


def _declined(value: bool) -> Any:
    def refused(case: EvaluationCase, output: Any) -> bool:
        return value

    return refused


def test_declining_a_question_that_accepts_a_refusal_scores_one() -> None:
    scorer = AcceptedRefusal(refused=_declined(True))

    result = asyncio.run(scorer(_case(), PredictionResult(answer="There is no app dimension in this data.")))

    assert result.scores["refusal"] == pytest.approx(1.0)


def test_answering_a_question_whose_data_does_not_exist_scores_zero() -> None:
    """The fabrication case, and the reason this is a score rather than a skip: a top-30 app list
    from a table with no app column came from somewhere other than the source."""

    scorer = AcceptedRefusal(refused=_declined(False))

    result = asyncio.run(scorer(_case(), PredictionResult(answer="1. Tubi 4,102,118\n2. Pluto 3,884,001")))

    assert result.scores["refusal"] == pytest.approx(0.0)
    assert result.details["refusal"]["declined"] is False


def test_a_question_with_a_real_answer_does_not_apply() -> None:
    """None, not zero: an answer is not wrong for failing to refuse."""

    scorer = AcceptedRefusal(refused=_declined(True))

    assert asyncio.run(scorer(_case(accepted=None), PredictionResult(answer="468,471 impressions"))) is None


def test_an_empty_answer_is_not_a_refusal() -> None:
    """A refusal states what cannot be done and why. Silence is a failure that looks like one."""

    scorer = AcceptedRefusal(refused=_declined(True))

    result = asyncio.run(scorer(_case(), PredictionResult(answer="   ")))

    assert result.scores["refusal"] == pytest.approx(0.0)
    assert result.details["refusal"]["answer"] == "empty"


def test_a_check_that_fails_leaves_the_refusal_unmeasured() -> None:
    def unavailable(case: EvaluationCase, output: Any) -> bool:
        raise RuntimeError("the judge is unreachable")

    scorer = AcceptedRefusal(refused=unavailable)

    result = asyncio.run(scorer(_case(), PredictionResult(answer="no app data")))

    assert isinstance(result, Unmeasured)
    assert "unreachable" in result.reason


def test_a_wrapped_criterion_does_not_apply_to_a_correct_refusal() -> None:
    """This is the inversion being fixed. The reference disagrees with a correct refusal by design,
    so the criterion has to step aside rather than score it zero."""

    def figures(case: EvaluationCase, output: Any) -> float:
        raise AssertionError("the wrapped criterion should not run for an accepted refusal")

    wrapped = WhenNotRefused(criterion=figures, refused=_declined(True))

    assert asyncio.run(wrapped(_case(), PredictionResult(answer="no app data"))) is None


def test_a_wrapped_criterion_still_scores_an_answer_that_did_not_refuse() -> None:
    wrapped = WhenNotRefused(criterion=lambda case, output: 0.25, refused=_declined(False))

    assert asyncio.run(wrapped(_case(), PredictionResult(answer="1. Tubi"))) == pytest.approx(0.25)


def test_a_wrapped_criterion_scores_normally_when_no_refusal_is_accepted() -> None:
    def refused(case: EvaluationCase, output: Any) -> bool:
        raise AssertionError("the refusal check should not run when the case accepts no refusal")

    wrapped = WhenNotRefused(criterion=lambda case, output: 1.0, refused=refused)

    assert asyncio.run(wrapped(_case(accepted=None), PredictionResult(answer="x"))) == pytest.approx(1.0)


def test_a_wrapper_whose_check_fails_withholds_rather_than_scoring() -> None:
    """Falling through to the criterion would reinstate the inverted verdict, because on these
    questions the reference disagrees with the right answer."""

    def unavailable(case: EvaluationCase, output: Any) -> bool:
        raise RuntimeError("rate limited")

    wrapped = WhenNotRefused(criterion=lambda case, output: 0.0, refused=unavailable)

    result = asyncio.run(wrapped(_case(), PredictionResult(answer="no app data")))

    assert isinstance(result, Unmeasured)
    assert "could not be decided" in result.reason
