"""A case nothing could score is not a case the agent got wrong.

A scorer that checks an answer against a table reports nothing when the table holds no row to check
against. Counting that as 0 blames the agent for missing ground truth, so a suite can exclude it —
but only when asked, because a metric silently absent is usually a mistake.
"""

from __future__ import annotations

import pytest

from agent_evals import (
    DatasetManifest,
    EvaluationCase,
    EvaluationDataset,
    EvaluationVariant,
    PredictionResult,
    RunSettings,
    SuiteRule,
    case_scores,
    run_repeated,
    suite_verdict,
)

MEASURABLE = {"c1": 1.0, "c2": 0.0}
UNMEASURABLE = "c3"


async def _run() -> tuple[EvaluationDataset, object]:
    """Two cases the scorer can measure and one it cannot, as a table with no matching row behaves."""

    cases = [EvaluationCase(case_id, {}) for case_id in (*MEASURABLE, UNMEASURABLE)]

    def runner(case: EvaluationCase, variant: EvaluationVariant) -> PredictionResult:
        return PredictionResult(answer="x")

    def scorer(case: EvaluationCase, output: PredictionResult) -> dict[str, float]:
        if case.case_id == UNMEASURABLE:
            return {"available": 0.0}
        return {"quality": MEASURABLE[case.case_id], "available": 1.0}

    dataset = EvaluationDataset("d", "1", cases)
    run = await run_repeated(cases, [EvaluationVariant("v")], runner, scorer, RunSettings(repeats=1))
    return dataset, run


async def test_an_unmeasured_case_is_an_error_by_default() -> None:
    """A metric that quietly went missing is almost always a bug, so it is loud unless asked otherwise."""

    _, run = await _run()

    with pytest.raises(ValueError, match="did not produce metric 'quality'"):
        case_scores(run, "v", "quality")


async def test_it_can_be_excluded_when_the_suite_says_so() -> None:
    _, run = await _run()

    scores = case_scores(run, "v", "quality", unmeasured="exclude")

    assert set(scores) == set(MEASURABLE)


async def test_the_verdict_names_what_it_left_out() -> None:
    """Shrinking the denominator without saying so would overstate how much was checked."""

    dataset, run = await _run()
    manifest = DatasetManifest.from_dataset(dataset, suite="regression")

    verdict = suite_verdict(run, "v", manifest, SuiteRule("quality", unmeasured_cases="exclude"))

    assert verdict.unmeasured_case_ids == (UNMEASURABLE,)
    assert verdict.case_count == len(MEASURABLE)
    assert verdict.failing_case_ids == ("c2",)


async def test_a_run_where_everything_was_measured_excludes_nothing() -> None:
    dataset, run = await _run()
    manifest = DatasetManifest.from_dataset(dataset, suite="capability")

    verdict = suite_verdict(run, "v", manifest, SuiteRule("available", unmeasured_cases="exclude"))

    assert verdict.unmeasured_case_ids == ()
    assert verdict.case_count == len(MEASURABLE) + 1
