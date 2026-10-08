"""What attribution is allowed to read about one run, and what it could not see."""

from __future__ import annotations

from _attribution_builders import prediction, result, row

from agent_evals.attribution.facts import declared_empty, facts_of_result, facts_of_row, row_count_of
from agent_evals.core.steps import GenericStep


def test_a_live_result_knows_the_trajectory_existed_and_keeps_each_failed_step_message() -> None:
    output = prediction(steps=[GenericStep(tool="aggregate_report", error="timed out")])

    facts = facts_of_result("c1", result(output=output))

    assert facts.calls_known is True
    assert facts.calls[0].errored is True
    assert facts.calls[0].error == "timed out"


def test_a_recorded_row_carries_the_tool_status_and_the_row_count() -> None:
    facts = facts_of_row(row(tool_calls=[{"tool": "aggregate_report", "status": "ok", "result": {"row_count": 14}}]))

    assert facts.calls[0].row_count == 14
    assert facts.calls[0].empty is False


def test_a_runner_that_returned_no_trajectory_is_not_the_same_as_calling_no_tools() -> None:
    facts = facts_of_result("c1", result(output=prediction(trajectory=False)))

    assert facts.calls_known is False


def test_a_row_written_before_the_field_existed_reports_that_nobody_knows() -> None:
    """None, not False. Reading that silence as "no tools" is the one move that would blame an agent
    for the shape of the runner."""

    facts = facts_of_row(row(tool_calls=[], steps_recorded=None))

    assert facts.calls_known is None


def test_an_observation_with_no_row_count_is_silence_rather_than_zero() -> None:
    assert declared_empty({"rows": "some"}) is None
    assert declared_empty({"row_count": 0}) is True
    assert declared_empty([]) is True
    assert row_count_of({"row_count": True}) is None


def test_a_project_may_supply_its_own_empty_result_reader() -> None:
    facts = facts_of_row(
        row(tool_calls=[{"tool": "t", "status": "ok", "result": {"n": 0}}]),
        empty_result=lambda observation: observation.get("n") == 0,
    )

    assert facts.empty_calls()[0].tool == "t"


def test_a_metric_is_found_under_its_rubric_key_or_bare() -> None:
    """SqlBreakdown cannot be a rubric criterion, so its scores arrive bare while a rubric
    criterion's arrive prefixed."""

    facts = facts_of_row(row(metrics={"accuracy.figures": 0.5, "breakdown.rows": 0.25}))

    assert facts.metric("accuracy.figures", "figures") == 0.5
    assert facts.metric("accuracy.breakdown.rows", "breakdown.rows") == 0.25
    assert facts.metric("nothing") is None


def test_a_result_whose_output_is_not_a_prediction_reports_nothing_known() -> None:
    facts = facts_of_result("c1", result(output={"answer": "raw"}))

    assert facts.calls_known is None
    assert facts.calls == ()
