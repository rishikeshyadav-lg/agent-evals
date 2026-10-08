"""Scoring an answer that was asked for a table, not a number.

Of 64 checkable questions mined from one agent's production traffic, 30 asked for a weekly trend and
15 for a per-placement split. A scalar check cannot see those answers at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_evals import EvaluationCase, PredictionResult
from agent_evals.core.prediction import Unmeasured
from agent_evals.scoring.breakdown import SqlBreakdown

WEEKS = [
    {"week": "2026-08-31", "impressions": 152_867.0, "spend": 1_956.70},
    {"week": "2026-09-07", "impressions": 73_633.0, "spend": 1_417.92},
    {"week": "2026-09-14", "impressions": 98_356.0, "spend": 2_788.34},
]
FIELDS = {"impressions": "impressions", "spend": "spend"}


def _execute(rows: list[dict[str, Any]] | None = None) -> Any:
    async def execute(sql: str, parameters: Any) -> list[dict[str, Any]]:
        return WEEKS if rows is None else rows

    return execute


def _case(**overrides: Any) -> EvaluationCase:
    declared = {"sql": "SELECT ...", "key": "week", "fields": dict(FIELDS), **overrides}
    return EvaluationCase("q", {}, expected={"breakdown": declared})


def _all_weeks_stated() -> Any:
    def read(answer: str, fields: Any, truth: Any) -> Any:
        return {row["week"]: {"impressions": row["impressions"], "spend": row["spend"]} for row in WEEKS}

    return read


def test_an_answer_stating_every_row_correctly_scores_one() -> None:
    scorer = SqlBreakdown(execute=_execute(), read_rows=_all_weeks_stated())

    result = asyncio.run(scorer(_case(), PredictionResult(answer="a weekly table")))

    assert result.scores["breakdown.rows"] == pytest.approx(1.0)
    assert result.scores["breakdown.figures"] == pytest.approx(1.0)


def test_a_skipped_row_lowers_coverage_and_not_the_figures() -> None:
    """An answer covering every week with wrong numbers and one covering half the weeks correctly
    are both wrong, and they need different fixes."""

    def read(answer: str, fields: Any, truth: Any) -> Any:
        row = WEEKS[0]
        return {row["week"]: {"impressions": row["impressions"], "spend": row["spend"]}}

    scorer = SqlBreakdown(execute=_execute(), read_rows=read)

    result = asyncio.run(scorer(_case(), PredictionResult(answer="one week only")))

    assert result.scores["breakdown.rows"] == pytest.approx(1 / 3)
    assert result.scores["breakdown.figures"] == pytest.approx(1.0)
    assert result.details["breakdown.rows"]["missing_keys"] == ["2026-09-07", "2026-09-14"]


def test_a_wrong_figure_in_a_stated_row_lowers_the_figures_and_not_coverage() -> None:
    def read(answer: str, fields: Any, truth: Any) -> Any:
        stated = {row["week"]: {"impressions": row["impressions"], "spend": row["spend"]} for row in WEEKS}
        stated["2026-09-07"] = {"impressions": 1.0, "spend": 1_417.92}
        return stated

    scorer = SqlBreakdown(execute=_execute(), read_rows=read)

    result = asyncio.run(scorer(_case(), PredictionResult(answer="a weekly table with one bad cell")))

    assert result.scores["breakdown.rows"] == pytest.approx(1.0)
    assert result.scores["breakdown.figures"] == pytest.approx(5 / 6)
    assert result.details["breakdown.figures"]["disagreed"]["2026-09-07"]["impressions"]["claimed"] == 1.0


def test_an_answer_giving_no_breakdown_at_all_scores_zero_rather_than_unmeasured() -> None:
    """It was asked for a breakdown and gave none of it. That is a verdict about the answer, not a
    failure to measure."""

    scorer = SqlBreakdown(execute=_execute(), read_rows=lambda answer, fields, truth: {})

    result = asyncio.run(scorer(_case(), PredictionResult(answer="just a total")))

    assert result.scores["breakdown.rows"] == pytest.approx(0.0)


def test_a_case_declaring_no_breakdown_does_not_apply() -> None:
    """None, not zero, so a suite can mix questions asking for a breakdown with questions that do
    not, and the ones that do not are left out of the mean."""

    scorer = SqlBreakdown(execute=_execute(), read_rows=_all_weeks_stated())

    assert asyncio.run(scorer(EvaluationCase("q", {}, expected={}), PredictionResult(answer="x"))) is None


def test_a_reader_that_fails_leaves_the_case_unmeasured() -> None:
    """A reader that broke read nothing, which is not the same as the answer stating nothing."""

    def unavailable(answer: str, fields: Any, truth: Any) -> Any:
        raise RuntimeError("the judge is unreachable")

    scorer = SqlBreakdown(execute=_execute(), read_rows=unavailable)

    result = asyncio.run(scorer(_case(), PredictionResult(answer="a weekly table")))

    assert isinstance(result, Unmeasured)
    assert "unreachable" in result.reason


def test_a_query_returning_no_rows_is_unmeasured() -> None:
    scorer = SqlBreakdown(execute=_execute([]), read_rows=_all_weeks_stated())

    result = asyncio.run(scorer(_case(), PredictionResult(answer="x")))

    assert isinstance(result, Unmeasured)
    assert "no rows" in result.reason


def test_a_query_missing_its_key_column_is_unmeasured() -> None:
    """Naming the column is the point: "could not key its rows" alone sends the author looking for a
    bug in the scorer when the fix is one word in their SQL."""

    scorer = SqlBreakdown(execute=_execute(), read_rows=_all_weeks_stated())

    result = asyncio.run(scorer(_case(key="placement"), PredictionResult(answer="x")))

    assert isinstance(result, Unmeasured)
    assert "placement" in result.reason


def test_a_breakdown_with_no_key_or_fields_is_unmeasured() -> None:
    scorer = SqlBreakdown(execute=_execute(), read_rows=_all_weeks_stated())

    result = asyncio.run(scorer(_case(key=""), PredictionResult(answer="x")))

    assert isinstance(result, Unmeasured)


def test_rows_the_agent_returned_as_data_are_preferred_to_reading_the_answer() -> None:
    """A table handed back as data needs neither parsing nor judging, and is exact on every run."""

    def never(answer: str, fields: Any, truth: Any) -> Any:
        raise AssertionError("the reader should not run when the agent supplied its rows")

    scorer = SqlBreakdown(execute=_execute(), read_rows=never)
    supplied = {row["week"]: {"impressions": row["impressions"], "spend": row["spend"]} for row in WEEKS}

    result = asyncio.run(scorer(_case(), PredictionResult(answer="prose", extra={"rows": supplied})))

    assert result.scores["breakdown.figures"] == pytest.approx(1.0)


def test_a_row_the_answer_invented_is_reported_without_lowering_coverage() -> None:
    """An extra week is worth seeing and is not a missing one, so it is recorded and not scored."""

    def read(answer: str, fields: Any, truth: Any) -> Any:
        stated = {row["week"]: {"impressions": row["impressions"], "spend": row["spend"]} for row in WEEKS}
        stated["2026-10-05"] = {"impressions": 50.0, "spend": 5.0}
        return stated

    scorer = SqlBreakdown(execute=_execute(), read_rows=read)

    result = asyncio.run(scorer(_case(), PredictionResult(answer="a weekly table plus a week that does not exist")))

    assert result.scores["breakdown.rows"] == pytest.approx(1.0)
    assert result.details["breakdown.rows"]["extra_keys"] == ["2026-10-05"]
