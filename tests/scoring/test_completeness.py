"""Whether the answer covered what was asked, in its two halves.

Some of what a question asks for is countable and a query settles it. The rest is not: a question
asking for notable trends is answered or it is not, and only something that reads the answer can
say which.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_evals import EvaluationCase, PredictionResult, Unmeasured
from agent_evals.scoring.completeness import Completeness

CASE, OUTPUT = EvaluationCase("q", {}), PredictionResult(answer="an answer")


def _score(criterion: Completeness) -> object:
    return asyncio.run(criterion(CASE, OUTPUT))


def test_countable_coverage_is_reported_as_the_fraction() -> None:
    result = _score(Completeness(coverage=lambda case, output: 2 / 3))

    assert result.scores["completeness"] == pytest.approx(2 / 3)


def test_an_omission_overrides_full_coverage() -> None:
    """A question wanting trends is not three-quarters answered because the numbers were right."""

    result = _score(Completeness(coverage=lambda case, output: 1.0, omission_of=lambda case, output: True))

    assert result.scores["completeness"] == pytest.approx(0.0)
    assert result.details["completeness"] == {"omission": True, "coverage": 1.0}


def test_a_reading_check_finding_nothing_does_not_establish_completeness() -> None:
    """It looked and found nothing missing, which is not the same as nothing being missing. The
    same reason grounding is a failure code and never a number."""

    result = _score(Completeness(omission_of=lambda case, output: False))

    assert isinstance(result, Unmeasured)


def test_a_reading_check_alone_can_still_lower_the_score() -> None:
    """The asymmetry: it can report an omission without being able to confirm the absence of one."""

    result = _score(Completeness(omission_of=lambda case, output: True))

    assert result.scores["completeness"] == pytest.approx(0.0)


def test_nothing_configured_is_unmeasured_not_perfect() -> None:
    assert isinstance(_score(Completeness()), Unmeasured)


def test_an_unmeasurable_coverage_carries_its_reason_through() -> None:
    result = _score(Completeness(coverage=lambda case, output: Unmeasured("no reference query")))

    assert isinstance(result, Unmeasured)
    assert result.reason == "no reference query"


def test_a_configured_check_that_cannot_run_withholds_rather_than_reporting_half() -> None:
    """Reporting the coverage fraction alone would say completeness was assessed when only the
    countable half was. A check that was asked for and could not run leaves the rest unknown."""

    def unavailable(case: EvaluationCase, output: object) -> bool:
        raise RuntimeError("the reading check is unavailable")

    result = _score(Completeness(coverage=lambda case, output: 0.5, omission_of=unavailable))

    assert isinstance(result, Unmeasured)
    assert "unavailable" in result.reason


def test_a_coverage_scorer_that_raises_does_not_take_the_case_down() -> None:
    def broken(case: EvaluationCase, output: object) -> float:
        return 1 / 0

    result = _score(Completeness(coverage=broken))

    assert isinstance(result, Unmeasured)
    assert "ZeroDivisionError" in result.reason
