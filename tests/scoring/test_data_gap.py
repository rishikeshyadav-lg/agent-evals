"""Whether an answer said what it could not tell you.

23 of 50 hand-reviewed rubrics require a caveat the answer must state. Nothing checked it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_evals import EvaluationCase, PredictionResult
from agent_evals.core.prediction import Unmeasured
from agent_evals.scoring.data_gap import DataGapStated

GAPS = ["reach is unavailable for this campaign", "the most recent week is still in flight"]


def _case(gaps: Any = GAPS) -> EvaluationCase:
    expected: dict[str, Any] = {} if gaps is None else {"data_gaps": gaps}
    return EvaluationCase("q", {"prompt": "how did it do"}, expected=expected)


def _states(*mentioned: str) -> Any:
    def states(case: EvaluationCase, output: Any, gap: str) -> bool:
        return gap in mentioned

    return states


def test_stating_every_required_limitation_scores_one() -> None:
    scorer = DataGapStated(states=_states(*GAPS))

    result = asyncio.run(scorer(_case(), PredictionResult(answer="reach is unavailable; the week is in flight")))

    assert result.scores["data_gap"] == pytest.approx(1.0)


def test_stating_some_of_them_scores_the_share() -> None:
    """A partially caveated answer is partially right, which is why the check runs per gap."""

    scorer = DataGapStated(states=_states(GAPS[0]))

    result = asyncio.run(scorer(_case(), PredictionResult(answer="reach is unavailable")))

    assert result.scores["data_gap"] == pytest.approx(0.5)
    assert result.details["data_gap"]["missing"] == [GAPS[1]]


def test_stating_none_of_them_scores_zero() -> None:
    """Zero is a verdict here only because the requirement came from the case, so its absence from
    the answer is known rather than guessed."""

    scorer = DataGapStated(states=_states())

    result = asyncio.run(scorer(_case(), PredictionResult(answer="impressions were 468,471")))

    assert result.scores["data_gap"] == pytest.approx(0.0)


def test_a_question_with_no_limitation_does_not_apply() -> None:
    scorer = DataGapStated(states=_states())

    assert asyncio.run(scorer(_case(gaps=None), PredictionResult(answer="x"))) is None


def test_one_gap_may_be_declared_as_a_plain_string() -> None:
    scorer = DataGapStated(states=_states("reach is unavailable for this campaign"))

    result = asyncio.run(scorer(_case(gaps=GAPS[0]), PredictionResult(answer="reach is unavailable")))

    assert result.scores["data_gap"] == pytest.approx(1.0)


def test_an_empty_answer_states_no_limitation() -> None:
    scorer = DataGapStated(states=_states(*GAPS))

    result = asyncio.run(scorer(_case(), PredictionResult(answer="")))

    assert result.scores["data_gap"] == pytest.approx(0.0)
    assert result.details["data_gap"]["answer"] == "empty"


def test_a_reader_that_fails_leaves_the_criterion_unmeasured() -> None:
    """Not zero. A reader that broke is a verdict about the reader, and scoring on it would call a
    caveated answer silent."""

    def unavailable(case: EvaluationCase, output: Any, gap: str) -> bool:
        raise RuntimeError("the judge is unreachable")

    scorer = DataGapStated(states=unavailable)

    result = asyncio.run(scorer(_case(), PredictionResult(answer="reach is unavailable")))

    assert isinstance(result, Unmeasured)
    assert "could not be read" in result.reason
