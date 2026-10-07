"""The SQL-reference example runs offline and reports each failure as the kind it actually is."""

from __future__ import annotations

import asyncio
import importlib.util

from _paths import EXAMPLES

EXAMPLE = EXAMPLES / "agent_evals_sql_reference" / "flow.py"


def _report() -> str:
    spec = importlib.util.spec_from_file_location("agent_evals_sql_reference_flow", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return asyncio.run(module.main())


def test_the_example_runs_with_no_database_installed() -> None:
    assert "Scorecard" in _report()


def test_a_wrong_figure_is_named_with_both_numbers() -> None:
    assert "clicks said 980, table says 615" in _report()


def test_an_omitted_figure_is_reported_as_omitted_not_wrong() -> None:
    report = _report()

    assert "never stated clicks" in report
    assert "autumn**: clicks said" not in report


def test_a_question_the_table_cannot_answer_is_set_aside() -> None:
    """Scoring winter zero would blame the agent for a row that does not exist."""

    report = _report()

    assert "winter**: not checked" in report
    assert "3 used, 1 excluded" in report
