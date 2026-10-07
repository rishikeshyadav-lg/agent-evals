"""A rubric must not invent accuracy from the criteria that happened to work.

If the criterion checking figures cannot reach the table, the weighted average of whatever else
scored is not accuracy. Reporting it as accuracy produced a confident 1.0 for an answer nobody had
checked, and a 0.0 for a case nobody could check. Both are the failure this library exists to
prevent: not measured is not zero, and it is not full marks either.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_evals import EvaluationCase, PredictionResult, Unmeasured, WeightedRubric
from agent_evals.scoring.answer import AnswerRubric

CASE, OUTPUT = EvaluationCase("c1", {}), PredictionResult(answer="x")
NO_TRUTH = "the query returned no rows"


def _scorer(value):
    def criterion(case: EvaluationCase, output: object):
        return value

    return criterion


def _run(**criteria):
    rubric = AnswerRubric(
        criteria={name: _scorer(value) for name, value in criteria.items()},
        rubric=WeightedRubric(weights=dict.fromkeys(criteria, 1.0)),
    )
    return asyncio.run(rubric(CASE, OUTPUT))


def test_one_unmeasurable_criterion_withholds_the_headline() -> None:
    """Scoring 1.0 here would say the answer was perfect when its figures were never checked."""

    result = _run(figures=Unmeasured(NO_TRUTH), completeness=1.0)

    assert "accuracy" not in result.scores
    assert result.scores["accuracy.completeness"] == 1.0


def test_nothing_measurable_is_not_a_zero() -> None:
    """A case nobody could score must not become a regression failure."""

    result = _run(figures=Unmeasured(NO_TRUTH))

    assert "accuracy" not in result.scores


def test_the_reason_reaches_the_report() -> None:
    """A metric that is absent cannot carry a detail, so the rubric reports that it was unmeasured."""

    result = _run(figures=Unmeasured(NO_TRUTH), completeness=1.0)

    assert result.scores["accuracy.measured"] == 0.0
    detail = result.details["accuracy.measured"]
    assert detail["unmeasured"] == {"figures": NO_TRUTH}


def test_a_fully_measured_answer_still_reports_accuracy() -> None:
    result = _run(figures=1.0, completeness=0.0)

    assert result.scores["accuracy"] == pytest.approx(0.5)
    assert result.scores["accuracy.measured"] == 1.0


def test_a_criterion_that_does_not_apply_is_not_unmeasurable() -> None:
    """None still means "nothing here to judge", which leaves the denominator and keeps the headline."""

    result = _run(figures=None, completeness=1.0)

    assert result.scores["accuracy"] == pytest.approx(1.0)
    assert result.scores["accuracy.measured"] == 1.0


def test_a_criterion_explains_itself() -> None:
    """A criterion's own detail must survive into the report, or a disagreement cannot be acted on."""

    from agent_evals import ScoreResult

    result = _run(figures=ScoreResult(0.0, feedback="clicks: said 380, table says 400"))

    assert result.details["accuracy.figures"]["feedback"] == "clicks: said 380, table says 400"
