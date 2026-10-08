"""Accuracy as named criteria rather than one number.

An answer can state every figure correctly and still be about the wrong customer or leave out half
the question. Averaging those into one score hides which one happened, and they have different fixes.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_evals import EvaluationCase, PredictionResult, WeightedRubric
from agent_evals.scoring.answer import SUGGESTED_CRITERIA, AnswerRubric, suggested_rubric

CASE, OUTPUT = EvaluationCase("c1", {}), PredictionResult(answer="x")


def _fixed(score: float | None):
    def scorer(case: EvaluationCase, output: object) -> float | None:
        return score

    return scorer


def _rubric(**scores: float | None) -> AnswerRubric:
    weights = {name: SUGGESTED_CRITERIA[name] for name in scores}
    return AnswerRubric(
        criteria={name: _fixed(score) for name, score in scores.items()},
        rubric=WeightedRubric(weights=weights),
    )


def _run(rubric: AnswerRubric):
    return asyncio.run(rubric(CASE, OUTPUT))


def test_the_headline_and_every_criterion_are_reported_together() -> None:
    """A reader needs the number and the parts behind it in the same place."""

    result = _run(_rubric(figures=1.0, completeness=0.5))

    assert result.scores["accuracy"] == pytest.approx((0.40 * 1.0 + 0.15 * 0.5) / 0.55)
    assert result.scores["accuracy.figures"] == 1.0
    assert result.scores["accuracy.completeness"] == 0.5


def test_right_figures_do_not_hide_a_wrong_answer() -> None:
    """The whole point: perfect numbers about the wrong thing is not a good answer."""

    result = _run(_rubric(figures=1.0, scope=0.0))

    assert result.scores["accuracy.figures"] == 1.0
    assert result.scores["accuracy"] < 0.7


def test_a_criterion_that_does_not_apply_leaves_the_denominator() -> None:
    """A question with no figures in it cannot have its figures be wrong, so it is not scored zero."""

    result = _run(_rubric(figures=1.0, completeness=1.0, interpretation=None))

    assert result.scores["accuracy"] == pytest.approx(1.0)
    assert "accuracy.interpretation" not in result.scores
    assert result.details["accuracy"]["applicable"] == ["figures", "completeness"]


def test_the_weights_are_renormalised_over_what_applied() -> None:
    result = _run(_rubric(figures=1.0, completeness=0.0, interpretation=None))
    weights = result.details["accuracy"]["effective_weights"]

    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["figures"] == pytest.approx(0.40 / 0.55)


def test_a_criterion_without_a_weight_is_refused() -> None:
    """The error path: a scorer nobody weighted would run and then be silently ignored."""

    with pytest.raises(ValueError, match="scorers without weights"):
        AnswerRubric(criteria={"figures": _fixed(1.0)}, rubric=WeightedRubric(weights={"scope": 1.0}))


def test_a_criterion_scorer_reporting_several_numbers_is_refused() -> None:
    """One criterion is one score; several would make the roll-up meaningless."""

    def two(case: EvaluationCase, output: object) -> dict[str, float]:
        return {"a": 1.0, "b": 1.0}

    rubric = AnswerRubric(criteria={"figures": two}, rubric=WeightedRubric(weights={"figures": 1.0}))

    with pytest.raises(ValueError, match="must report one score"):
        _run(rubric)


def test_the_suggested_rubric_covers_the_five_criteria() -> None:
    assert set(suggested_rubric().weights) == set(SUGGESTED_CRITERIA)
    assert sum(SUGGESTED_CRITERIA.values()) == pytest.approx(1.0)


def _figures_only_rubric() -> AnswerRubric:
    """A rubric with one criterion wired, which is the state every real setup starts in."""

    return AnswerRubric(
        criteria={"figures": lambda case, output: 1.0},
        rubric=WeightedRubric(weights={"figures": 1.0}),
    )


def test_a_question_needing_more_than_is_scored_gets_no_headline() -> None:
    """The failure this exists for. A real three-part question -- metrics, trends, recommended
    actions -- scored 1.000 on an answer that gave only the metrics."""

    case = EvaluationCase("q", {}, expected={"requires": ["figures", "interpretation"]})

    result = asyncio.run(_figures_only_rubric()(case, PredictionResult(answer="spend was $8,392,901")))

    assert "accuracy" not in result.scores
    assert result.scores["accuracy.figures"] == pytest.approx(1.0)
    assert "interpretation" in result.details["accuracy.measured"]["unmeasured"]


def test_the_reason_names_what_went_unchecked() -> None:
    """"Not measured" without saying which part is a dead end for whoever reads the report."""

    case = EvaluationCase("q", {}, expected={"requires": ["interpretation"]})

    result = asyncio.run(_figures_only_rubric()(case, PredictionResult(answer="anything")))

    assert "no criterion scores it" in result.details["accuracy.measured"]["unmeasured"]["interpretation"]


def test_requiring_only_what_is_wired_still_reports_a_headline() -> None:
    """The guard must not withhold everything; a case whose needs are met scores normally."""

    case = EvaluationCase("q", {}, expected={"requires": ["figures"]})

    result = asyncio.run(_figures_only_rubric()(case, PredictionResult(answer="spend was $1")))

    assert result.scores["accuracy"] == pytest.approx(1.0)


def test_a_case_that_declares_nothing_behaves_as_before() -> None:
    """Existing datasets declare no requirements and must keep working unchanged."""

    result = asyncio.run(_figures_only_rubric()(EvaluationCase("q", {}), PredictionResult(answer="x")))

    assert result.scores["accuracy"] == pytest.approx(1.0)


def test_a_criterion_that_did_not_apply_still_counts_as_unchecked_when_required() -> None:
    """None means "does not apply to this question". If the case says it does apply, the two
    disagree, and the honest reading is that nobody checked it."""

    rubric = AnswerRubric(
        criteria={"figures": lambda case, output: 1.0, "scope": lambda case, output: None},
        rubric=WeightedRubric(weights={"figures": 0.7, "scope": 0.3}),
    )
    case = EvaluationCase("q", {}, expected={"requires": ["scope"]})

    result = asyncio.run(rubric(case, PredictionResult(answer="x")))

    assert "accuracy" not in result.scores
    assert "did not apply" in result.details["accuracy.measured"]["unmeasured"]["scope"]


def test_a_criterion_that_raises_is_unmeasured_not_a_zero() -> None:
    """A judge that is down, rate-limited, or returned unparseable text is a failure of the
    measurement, not of the agent. Left to propagate it becomes a case error, and a case error is
    scored 0.0 -- so a flaky model would quietly report a good answer as wrong."""

    def unreachable(case: EvaluationCase, output: object) -> float:
        raise RuntimeError("the judge was unreachable")

    rubric = AnswerRubric(
        criteria={"interpretation": unreachable},
        rubric=WeightedRubric(weights={"interpretation": 1.0}),
    )

    result = asyncio.run(rubric(EvaluationCase("q", {}), PredictionResult(answer="a good answer")))

    assert "accuracy" not in result.scores
    assert "unreachable" in result.details["accuracy.measured"]["unmeasured"]["interpretation"]


def test_the_raised_reason_names_the_exception_so_a_bug_is_visible() -> None:
    """Swallowing it as a bare "not measured" would hide a bug in the criterion itself."""

    def broken(case: EvaluationCase, output: object) -> float:
        return 1 / 0

    rubric = AnswerRubric(criteria={"figures": broken}, rubric=WeightedRubric(weights={"figures": 1.0}))

    result = asyncio.run(rubric(EvaluationCase("q", {}), PredictionResult(answer="x")))

    assert "ZeroDivisionError" in result.details["accuracy.measured"]["unmeasured"]["figures"]
