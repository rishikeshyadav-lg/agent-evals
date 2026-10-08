"""One dominant cause per bad run, by first match over a causal precedence."""

from __future__ import annotations

import pytest
from _attribution_builders import row

from agent_evals.attribution.causes import DEFAULT_RULES, Cause, attribute, attribute_run
from agent_evals.attribution.facts import facts_of_row

OK_CALL = {"tool": "aggregate_report", "status": "ok", "result": {"row_count": 14}}
EMPTY_CALL = {"tool": "aggregate_report", "status": "ok", "result": {"row_count": 0}}


def _code(**kwargs) -> str | None:
    return attribute(facts_of_row(row(**kwargs))).code


def test_a_run_that_scored_well_is_attributed_no_cause_and_says_so() -> None:
    result = attribute(facts_of_row(row(metrics={"accuracy": 1.0})))

    assert result.cause is None
    assert result.attributable is True
    assert "scored 1.000" in result.reason


def test_a_failed_run_is_attributed_to_the_failure_and_not_to_calling_no_tools() -> None:
    """A timed-out run also has no tool calls and no answer, and every rule below would describe
    that silence as a choice the agent made."""

    assert _code(error="TimeoutError: no result within 600s", tool_calls=[], answer=None) == "run_failed"


def test_a_run_whose_criteria_all_went_unmeasured_does_not_blame_the_agent() -> None:
    result = attribute(
        facts_of_row(row(details={"accuracy.measured": {"unmeasured": {"figures": "the judge was unreachable"}}}))
    )

    assert result.code == "measurement_unavailable"
    assert result.cause.blames_agent is False


def test_an_unmeasured_criterion_does_not_acquit_a_measured_one_that_failed() -> None:
    """A judge that was down while the figures were checked and disagreed is a partial diagnosis,
    not an acquittal."""

    result = attribute(
        facts_of_row(
            row(
                metrics={"accuracy.figures": 0.25},
                tool_calls=[OK_CALL],
                details={"accuracy.measured": {"unmeasured": {"interpretation": "the judge was unreachable"}}},
            )
        )
    )

    assert result.code == "figures_wrong"
    assert result.unmeasured == {"interpretation": "the judge was unreachable"}


def test_a_completed_run_with_no_answer_is_attributed_to_that() -> None:
    assert _code(answer="   ", tool_calls=[OK_CALL]) == "no_answer"


def test_answering_without_calling_a_tool_is_attributed_when_the_record_proves_it() -> None:
    assert _code(tool_calls=[], steps_recorded=True) == "no_tool_calls"


def test_a_record_that_cannot_tell_is_never_attributed_to_calling_no_tools() -> None:
    """Asserting the cause from a row that recorded no trajectory would assert it from the shape of
    the runner."""

    assert _code(tool_calls=[], steps_recorded=None) != "no_tool_calls"
    assert _code(tool_calls=[], steps_recorded=False) != "no_tool_calls"


def test_a_failed_tool_call_outranks_the_wrong_figures_that_followed_it() -> None:
    code = _code(
        tool_calls=[{"tool": "aggregate_report", "status": "error", "result": None}],
        metrics={"accuracy.figures": 0.0},
    )

    assert code == "tool_error"


def test_an_empty_result_with_a_stated_figure_is_fabrication() -> None:
    """Seven of 56 runs in one recorded baseline stated confident figures while every tool returned
    no rows."""

    assert _code(tool_calls=[EMPTY_CALL], metrics={"accuracy.figures": 1.0}) == "fabricated_from_empty_result"


def test_an_empty_result_with_no_figure_established_is_not_fabrication() -> None:
    """An agent that correctly reports there was no data has the same empty result and is not wrong,
    so the stronger code needs the stronger evidence."""

    assert _code(tool_calls=[EMPTY_CALL], metrics={"accuracy": 0.0}) == "empty_tool_result"


def test_one_tool_returning_rows_means_the_answer_had_a_source() -> None:
    assert _code(tool_calls=[EMPTY_CALL, OK_CALL], metrics={"accuracy.figures": 0.5}) == "figures_wrong"


def test_a_rubric_failure_code_outranks_every_score_derived_cause() -> None:
    """AnswerRubric zeroes the headline on a failure code, so a score-derived cause below would be
    describing a number the rubric had already overruled."""

    result = attribute(
        facts_of_row(
            row(
                tool_calls=[OK_CALL],
                metrics={"accuracy.figures": 0.0, "accuracy.scope": 0.0},
                details={"accuracy": {"failure_codes": ["invented_figure"]}},
            )
        )
    )

    assert result.code == "failure_code"
    assert result.cause.evidence["failure_codes"] == ["invented_figure"]


def test_right_figures_about_the_wrong_campaign_are_attributed_to_scope() -> None:
    """Wrong scope produces wrong figures, so it is the upstream cause and fixing it fixes both."""

    code = _code(
        tool_calls=[OK_CALL],
        metrics={"accuracy.scope": 0.0, "accuracy.figures": 0.0},
        details={"accuracy.scope": {"expected": "109249", "answered_about": ["109778"]}},
    )

    assert code == "wrong_scope"


def test_a_table_that_was_asked_for_and_not_given_is_attributed_to_that() -> None:
    assert _code(tool_calls=[OK_CALL], metrics={"breakdown.rows": 0.0}) == "breakdown_missing"


def test_a_partial_table_is_a_different_cause_from_an_absent_one() -> None:
    code = _code(tool_calls=[OK_CALL], metrics={"breakdown.rows": 0.5, "breakdown.figures": 1.0})

    assert code == "breakdown_incomplete"


def test_an_omission_is_attributed_last() -> None:
    assert _code(tool_calls=[OK_CALL], metrics={"accuracy.completeness": 0.5}) == "incomplete"


def test_a_bad_run_nothing_explains_is_unattributable_and_says_why() -> None:
    """Reporting "no cause" would read as a clean bill of health for the case that most needs one."""

    result = attribute(facts_of_row(row(tool_calls=[OK_CALL], metrics={"accuracy": 0.0})))

    assert result.cause is None
    assert result.attributable is False
    assert "nothing recorded explains it" in result.reason


def test_the_runners_up_are_kept_so_the_order_is_not_load_bearing() -> None:
    result = attribute(
        facts_of_row(
            row(
                tool_calls=[{"tool": "t", "status": "error", "result": None}],
                metrics={"accuracy.figures": 0.0, "accuracy.completeness": 0.0},
            )
        )
    )

    assert result.code == "tool_error"
    assert [cause.code for cause in result.also] == ["figures_wrong", "incomplete"]


def test_a_project_may_replace_the_rule_list() -> None:
    def always(facts) -> Cause:
        return Cause(code="incomplete", detail="this project decides differently")

    always.code = "incomplete"

    result = attribute(facts_of_row(row(metrics={"accuracy": 0.0})), rules=[always])

    assert result.code == "incomplete"


def test_a_rule_that_raises_is_not_swallowed_into_a_wrong_cause() -> None:
    def broken(facts) -> Cause:
        raise RuntimeError("this rule is broken")

    broken.code = "incomplete"

    with pytest.raises(RuntimeError, match="broken"):
        attribute(facts_of_row(row(metrics={"accuracy": 0.0})), rules=[broken])


def test_a_run_with_no_headline_metric_is_attributed_rather_than_assumed_good() -> None:
    """That is exactly the case the rubric withheld a headline from."""

    result = attribute(facts_of_row(row(tool_calls=[], steps_recorded=True)))

    assert result.code == "no_tool_calls"


def test_every_row_of_a_variant_is_attributed_in_order() -> None:
    from _attribution_builders import run

    attributions = attribute_run(
        run(row(case_id="a", metrics={"accuracy": 1.0}), row(case_id="b", tool_calls=[], steps_recorded=True)),
        "prd",
    )

    assert [a.case_id for a in attributions] == ["a", "b"]
    assert [a.code for a in attributions] == [None, "no_tool_calls"]


def test_the_default_rules_are_ordered_causally() -> None:
    """A regression guard: reordering these silently changes every diagnosis a report makes."""

    assert [rule.code for rule in DEFAULT_RULES[:7]] == [
        "run_failed",
        "measurement_unavailable",
        "no_answer",
        "no_tool_calls",
        "tool_error",
        "fabricated_from_empty_result",
        "failure_code",
    ]
