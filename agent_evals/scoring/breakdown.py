"""Scoring an answer that was asked for a table, not a number.

`SqlReference` compares scalars, and most real questions do not ask for scalars. Of 64 checkable
questions mined from one agent's production traffic, 30 asked for a weekly trend, 15 for a
per-placement split and 7 for a per-creative one. Those answers are tables, and a scalar check
cannot see them: `verify` refuses a query returning five rows precisely because which one is "the"
answer is not for a tool to guess.

So this scores a breakdown as what it is -- a set of rows, each keyed by a dimension the question
asked to be broken down by. The reference query returns one row per key, the reader finds what the
answer stated for each key, and the comparison is per figure, arithmetic, as before.

Two scores, because they fail for different reasons and need different fixes. `rows` is how many of
the keys the answer stated at all: a weekly answer that skipped two weeks is incomplete. `figures`
is, of the rows it did state, how many carried the right numbers. An answer covering every week with
wrong figures and one covering half the weeks correctly are both wrong, and not in the same way.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..core.evaluation import EvaluationCase, _await_value
from ..core.prediction import MultiScoreResult, Unmeasured
from ..sql.executor import SqlExecutor
from .outcome import Tolerance, answer_of
from .reference import _as_number

logger = logging.getLogger(__name__)

CASE_KEY = "breakdown"
ROWS_KEY = "rows"

StatedRows = Mapping[str, Mapping[str, float | None]]
"""What the answer stated, per key, per field."""

RowReader = Callable[[str, Mapping[str, str], Mapping[str, Mapping[str, float]]], StatedRows | Awaitable[StatedRows]]
"""Reads what an answer stated for each key of a breakdown.

Given the truth, as `ClaimReader` is, and for the same reason: a reader asked "the table says this
week ran 152,867 impressions, does the answer state that?" can be checked against a person's
judgement later, while one asked "what does this answer say about week three?" invites a figure to
be invented.
"""


def _breakdown_from_case(case: EvaluationCase) -> Mapping[str, Any] | None:
    """The breakdown query a case declares, under `expected["breakdown"]`.

    Separate from `expected["reference"]` so one case can carry both: a question asking for totals
    *and* a weekly split is two checks, not a choice between them.
    """

    expected = case.expected
    if not isinstance(expected, Mapping):
        return None
    declared = expected.get(CASE_KEY)
    return declared if isinstance(declared, Mapping) else None


def _rows_from_output(output: Any) -> Mapping[str, Any]:
    """Rows the agent returned as data, under `PredictionResult.extra["rows"]`.

    Preferred over reading the answer for the same reason figures are: a table handed back as data
    needs neither parsing nor judging, and is the only path that is exact on every run.
    """

    extra = getattr(output, "extra", None)
    if not isinstance(extra, Mapping):
        return {}
    rows = extra.get(ROWS_KEY)
    return rows if isinstance(rows, Mapping) else {}


@dataclass(frozen=True, slots=True)
class SqlBreakdown:
    """Scores an answer's per-key figures against the rows a case's own query returns.

    `read_rows` is how the answer is read. There is no default: finding a week's figures in prose by
    proximity is the failure that cost this package a release, and a breakdown multiplies it by the
    number of rows. Pass `JudgeRows`, or a reader of your own that knows the agent's format.
    """

    execute: SqlExecutor
    read_rows: RowReader
    tolerances: Mapping[str, Tolerance] = field(default_factory=dict)
    default_tolerance: Tolerance = Tolerance("relative", 0.01)
    query_of: Callable[[EvaluationCase], Mapping[str, Any] | None] = _breakdown_from_case
    rows_of: Callable[[Any], Mapping[str, Any]] = _rows_from_output
    name: str = "breakdown"

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult | Unmeasured | None:
        truth = await self.ground_truth(case)
        if isinstance(truth, Unmeasured) or truth is None:
            return truth
        expected_rows, fields = truth

        structured = self._structured(expected_rows, fields, output)
        if structured is not None:
            stated = structured
        else:
            try:
                stated = dict(await _await_value(self.read_rows(str(answer_of(output)), fields, expected_rows)))
            except Exception as error:  # noqa: BLE001 -- a reader that broke read nothing
                logger.info("The breakdown reader raised", exc_info=True)
                return Unmeasured(f"the answer's rows could not be read: {type(error).__name__}: {error}")

        covered = [key for key in expected_rows if key in stated]
        if not covered:
            # Every key missing is a real verdict, not a failure to measure: the answer was asked
            # for a breakdown and gave none of it.
            return MultiScoreResult(
                {f"{self.name}.rows": 0.0},
                {f"{self.name}.rows": {"expected_keys": list(expected_rows), "stated_keys": []}},
            )

        matched, disagreed = self._compare(expected_rows, fields, stated, covered)
        total = sum(len(fields) for _ in covered)
        scores = {
            f"{self.name}.rows": len(covered) / len(expected_rows),
            f"{self.name}.figures": (matched / total) if total else 0.0,
        }
        details: dict[str, Mapping[str, Any]] = {
            f"{self.name}.rows": {
                "expected_keys": list(expected_rows),
                "missing_keys": [key for key in expected_rows if key not in stated],
                "extra_keys": [key for key in stated if key not in expected_rows],
            }
        }
        if disagreed:
            details[f"{self.name}.figures"] = {"disagreed": disagreed}
        return MultiScoreResult(scores, details)

    async def ground_truth(
        self, case: EvaluationCase
    ) -> tuple[Mapping[str, Mapping[str, float]], Mapping[str, str]] | Unmeasured | None:
        """The rows the case's query returns, keyed by its key column.

        `None` when the case declares no breakdown, so a suite can mix questions that ask for one
        with questions that do not.
        """

        declared = self.query_of(case)
        if not declared:
            return None
        sql = str(declared.get("sql", "")).strip()
        key_column = str(declared.get("key", "")).strip()
        fields = declared.get("fields")
        if not sql or not key_column or not isinstance(fields, Mapping) or not fields:
            return Unmeasured("the case's breakdown needs a sql, a key column and at least one field")

        try:
            rows = await self.execute(sql, dict(declared.get("parameters") or {}))
        except Exception as error:  # noqa: BLE001 -- a database that is down is not the agent's fault
            return Unmeasured(f"the breakdown query failed: {type(error).__name__}: {error}")
        if not rows:
            return Unmeasured("the breakdown query returned no rows, so there is nothing to compare against")

        keyed: dict[str, dict[str, float]] = {}
        for row in rows:
            if key_column not in row:
                return Unmeasured(f"the breakdown query returned no {key_column!r} column to key its rows by")
            key = str(row[key_column])
            values = {name: _as_number(row.get(column)) for name, column in fields.items()}
            present = {name: value for name, value in values.items() if value is not None}
            if present:
                keyed[key] = present
        if not keyed:
            return Unmeasured("the breakdown query returned rows but no figures in them")
        return keyed, {name: str(label) for name, label in fields.items()}

    def _structured(
        self, expected: Mapping[str, Mapping[str, float]], fields: Mapping[str, str], output: Any
    ) -> dict[str, Mapping[str, float | None]] | None:
        """Rows the agent handed back as data, when it covered at least one expected key."""

        supplied = self.rows_of(output)
        if not supplied:
            return None
        stated: dict[str, Mapping[str, float | None]] = {}
        for key in expected:
            row = supplied.get(key)
            if isinstance(row, Mapping):
                stated[key] = {name: _as_number(row.get(name)) for name in fields}
        return stated or None

    def _compare(
        self,
        expected: Mapping[str, Mapping[str, float]],
        fields: Mapping[str, str],
        stated: StatedRows,
        covered: Sequence[str],
    ) -> tuple[int, dict[str, Any]]:
        matched = 0
        disagreed: dict[str, Any] = {}
        for key in covered:
            said = stated.get(key) or {}
            for name in fields:
                want = expected[key].get(name)
                got = _as_number(said.get(name))
                if want is None or got is None:
                    disagreed.setdefault(key, {})[name] = {"expected": want, "claimed": got}
                    continue
                tolerance = self.tolerances.get(name, self.default_tolerance)
                if tolerance.matches(got, want, abbreviated=False):
                    matched += 1
                else:
                    disagreed.setdefault(key, {})[name] = {"expected": want, "claimed": got}
        return matched, disagreed


__all__ = ["CASE_KEY", "ROWS_KEY", "RowReader", "SqlBreakdown", "StatedRows"]
