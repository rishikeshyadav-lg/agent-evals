"""What went wrong across a whole run, ranked, with the cases named."""

from __future__ import annotations

import pytest
from _attribution_builders import row, run

from agent_evals.attribution.aggregate import cause_report, failure_code_report
from agent_evals.attribution.causes import attribute_run

OK_CALL = {"tool": "aggregate_report", "status": "ok", "result": {"row_count": 14}}


def _report(*rows):
    repeated = run(*rows)
    return cause_report(attribute_run(repeated, "prd"), "prd", runs=len(repeated.rows))


def test_causes_are_ranked_by_the_runs_they_explain_with_the_cases_named() -> None:
    """A count with no case ids is a number nobody can check."""

    report = _report(
        row(case_id="a", tool_calls=[], steps_recorded=True),
        row(case_id="b", tool_calls=[], steps_recorded=True),
        row(case_id="c", tool_calls=[OK_CALL], metrics={"accuracy.completeness": 0.5}),
    )

    assert report.dominant.code == "no_tool_calls"
    assert report.dominant.runs == 2
    assert list(report.dominant.cases) == ["a", "b"]


def test_a_cause_that_is_our_own_gap_is_counted_apart_from_the_ranking() -> None:
    """Letting it rank would put the loudest number in the report on something the agent did not do."""

    report = _report(
        row(case_id="a", details={"accuracy.measured": {"unmeasured": {"figures": "judge down"}}}),
        row(case_id="b", tool_calls=[OK_CALL], metrics={"accuracy.completeness": 0.0}),
    )

    assert report.blamed_on_measurement == 1
    assert [count.code for count in report.counts] == ["incomplete"]


def test_unattributed_bad_runs_are_listed_with_their_reasons() -> None:
    report = _report(row(case_id="a", tool_calls=[OK_CALL], metrics={"accuracy": 0.0}))

    assert report.unattributed[0][0] == "a"
    assert "nothing recorded explains it" in report.unattributed[0][2]


def test_runners_up_are_counted_separately_from_the_headline_causes() -> None:
    report = _report(
        row(
            case_id="a",
            tool_calls=[{"tool": "t", "status": "error", "result": None}],
            metrics={"accuracy.completeness": 0.0},
        )
    )

    assert [c.code for c in report.counts] == ["tool_error"]
    assert [c.code for c in report.runner_up_counts] == ["incomplete"]


def test_ties_break_by_code_name_so_two_reports_agree() -> None:
    report = _report(
        row(case_id="a", tool_calls=[OK_CALL], metrics={"accuracy.completeness": 0.5}),
        row(case_id="b", tool_calls=[OK_CALL], metrics={"accuracy.figures": 0.5}),
    )

    assert [c.code for c in report.counts] == ["figures_wrong", "incomplete"]


def test_failure_codes_are_counted_from_both_details_without_double_counting() -> None:
    """The rubric gathers codes before deciding whether to withhold a headline, so the same code can
    appear under both keys for one row."""

    report = failure_code_report(
        run(
            row(
                case_id="a",
                details={
                    "accuracy": {"failure_codes": ["invented_figure"]},
                    "accuracy.measured": {"failure_codes": ["invented_figure"]},
                },
            )
        ),
        "prd",
    )

    assert report.runs_with_codes == 1
    assert report.counts[0].runs == 1


def test_unmeasured_criteria_are_reported_beside_the_codes_rather_than_mixed_in() -> None:
    """A code is a verdict about an answer; an unmeasured criterion is a verdict about us."""

    report = failure_code_report(
        run(row(case_id="a", details={"accuracy.measured": {"unmeasured": {"interpretation": "judge down"}}})),
        "prd",
    )

    assert report.counts == ()
    assert report.unmeasured[0].code == "interpretation"


def test_a_variant_with_no_rows_raises() -> None:
    with pytest.raises(ValueError, match="no rows for variant"):
        failure_code_report(run(row()), "rc1")
