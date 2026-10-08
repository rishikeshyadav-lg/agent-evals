"""Asking a model whether an answer's conclusions follow, and keeping its verdict quarantined.

The only criterion of accuracy that cannot be settled by arithmetic, and the only one that can make
a number worse by existing. It is reported beside the headline, never inside it, until agreement
with a person has been measured.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_evals import AnswerRubric, EvaluationCase, PredictionResult, Unmeasured, WeightedRubric
from agent_evals.scoring.interpretation import Interpretation

CASE = EvaluationCase("q", {"prompt": "How is 109249 doing? Note any trends."})
OUTPUT = PredictionResult(answer="Spend $8.3M. Delivery is pacing ahead of goal.")


def _judged(reply: str) -> object:
    return asyncio.run(Interpretation(client=lambda prompt: reply)(CASE, OUTPUT))


def test_a_supported_interpretation_scores_one() -> None:
    assert _judged('{"outcome": "supported", "codes": []}').scores["interpretation"] == pytest.approx(1.0)


def test_an_unsupported_one_scores_zero_and_keeps_its_codes() -> None:
    """`JudgeScorer` drops the codes, which is the reason this is not built on it."""

    result = _judged('{"outcome": "unsupported", "codes": ["unsupported_pacing"]}')

    assert result.scores["interpretation"] == pytest.approx(0.0)
    assert result.details["interpretation"]["codes"] == ["unsupported_pacing"]


def test_json_wrapped_in_prose_is_still_read() -> None:
    """A model asked for JSON usually supplies a sentence around it."""

    result = _judged('Here is my verdict: {"outcome": "partly_supported", "codes": []}')

    assert result.scores["interpretation"] == pytest.approx(0.5)


def test_an_answer_drawing_no_conclusion_does_not_apply() -> None:
    """Nothing to interpret is different from interpreting badly, so it leaves the denominator."""

    assert _judged('{"outcome": "no_claims", "codes": []}') is None


def test_an_unreadable_reply_is_unmeasured_not_zero() -> None:
    """Scoring zero would call the answer wrong on the strength of the judge malfunctioning."""

    result = _judged("I think it is probably fine?")

    assert isinstance(result, Unmeasured)
    assert "could not be read" in result.reason


def test_an_outcome_with_no_score_is_unmeasured() -> None:
    assert isinstance(_judged('{"outcome": "maybe", "codes": []}'), Unmeasured)


def test_an_unreachable_judge_is_unmeasured() -> None:
    def down(prompt: str) -> str:
        raise RuntimeError("rate limited")

    result = asyncio.run(Interpretation(client=down)(CASE, OUTPUT))

    assert isinstance(result, Unmeasured)
    assert "unreachable" in result.reason


def test_a_case_with_no_question_cannot_be_judged() -> None:
    result = asyncio.run(Interpretation(client=lambda p: "{}")(EvaluationCase("q", {}), OUTPUT))

    assert isinstance(result, Unmeasured)


def _quarantined(client: object) -> AnswerRubric:
    return AnswerRubric(
        criteria={"figures": lambda case, output: 1.0},
        rubric=WeightedRubric(weights={"figures": 1.0}),
        reported_only={"interpretation": Interpretation(client=client)},
    )


@pytest.mark.parametrize(
    "reply",
    ['{"outcome":"supported","codes":[]}', '{"outcome":"unsupported","codes":["x"]}', "nonsense"],
)
def test_the_judge_never_moves_the_headline(reply: str) -> None:
    """The whole point of the quarantine. An unvalidated judge must not move a number people act on."""

    result = asyncio.run(_quarantined(lambda prompt: reply)(CASE, OUTPUT))

    assert result.scores["accuracy"] == pytest.approx(1.0)


def test_a_broken_judge_cannot_void_the_headline_either() -> None:
    """One Unmeasured from a weighted criterion withholds accuracy. A quarantined one must not,
    or a flaky model would void every case in the run."""

    def down(prompt: str) -> str:
        raise RuntimeError("rate limited")

    result = asyncio.run(_quarantined(down)(CASE, OUTPUT))

    assert result.scores["accuracy"] == pytest.approx(1.0)
    assert "accuracy.interpretation" not in result.scores


def test_the_reported_score_is_marked_experimental() -> None:
    """A reader has to be able to tell which numbers were validated and which were not."""

    result = asyncio.run(_quarantined(lambda p: '{"outcome":"supported","codes":[]}')(CASE, OUTPUT))

    assert result.details["accuracy.interpretation"]["experimental"] is True
    assert result.details["accuracy.interpretation"]["weighted"] is False


def test_a_criterion_cannot_be_both_weighted_and_quarantined() -> None:
    """Scoring it twice, once inside the headline and once beside it, is never what was meant."""

    with pytest.raises(ValueError, match="not both"):
        AnswerRubric(
            criteria={"figures": lambda case, output: 1.0},
            rubric=WeightedRubric(weights={"figures": 1.0}),
            reported_only={"figures": lambda case, output: 1.0},
        )


def test_a_judge_with_nothing_to_judge_does_not_withhold_a_required_headline() -> None:
    """Caught by running all five criteria together. An answer that omitted the trends it was asked
    for had its headline withheld, so the suite excluded the case and the failure vanished from the
    mean instead of dragging it down. "Looked and found nothing to judge" is a measurement; "could
    not run" is not, and only the second leaves a requirement unmet."""

    rubric = AnswerRubric(
        criteria={"figures": lambda case, output: 1.0},
        rubric=WeightedRubric(weights={"figures": 1.0}),
        reported_only={"interpretation": Interpretation(client=lambda p: '{"outcome":"no_claims","codes":[]}')},
    )
    case = EvaluationCase("q", {"prompt": "How is it doing?"}, expected={"requires": ["interpretation"]})

    result = asyncio.run(rubric(case, OUTPUT))

    assert result.scores["accuracy"] == pytest.approx(1.0)


def test_a_judge_that_could_not_run_does_withhold_a_required_headline() -> None:
    """The other half of the same distinction: the question needed it and nobody measured it."""

    def down(prompt: str) -> str:
        raise RuntimeError("rate limited")

    rubric = AnswerRubric(
        criteria={"figures": lambda case, output: 1.0},
        rubric=WeightedRubric(weights={"figures": 1.0}),
        reported_only={"interpretation": Interpretation(client=down)},
    )
    case = EvaluationCase("q", {"prompt": "How is it doing?"}, expected={"requires": ["interpretation"]})

    result = asyncio.run(rubric(case, OUTPUT))

    assert "accuracy" not in result.scores
