"""Checking an agent's figures against the table that holds the truth.

The case carries the query that establishes what the right answer is. This runs it, finds each
field's figure in the agent's reply, compares them within a tolerance you set per field, and reports
which field disagreed and by how much. That last part is the point: knowing a run scored 0.6 tells
you nothing you can fix, and knowing it said 380 clicks where the table says 400 tells you a lot.

It reports two things from one query, because a figure never mentioned and a figure stated wrongly
are different failures:

  figures           of the figures the answer stated, the share that match the table
  figures.coverage  of the figures required, the share the answer stated at all

So an answer that omits spend entirely scores clean on `figures` and loses on `figures.coverage`,
which is what feeds a completeness criterion. An answer that states spend wrongly loses on `figures`.

When the table cannot answer — no rows, a missing column, a query that failed — this reports nothing
rather than guessing. A score of zero would say the agent was wrong, when the truth is that nobody
checked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..core.evaluation import EvaluationCase
from ..core.prediction import MultiScoreResult, Unmeasured
from ..sql.executor import SqlExecutor
from .claims import DEFAULT_WINDOW, StatedNumber, numbers_by_label
from .outcome import Tolerance, answer_of

CASE_KEY = "reference"
FIGURES_KEY = "figures"


def _query_from_case(case: EvaluationCase) -> Mapping[str, Any] | None:
    """The query a case declares, under `expected["reference"]`.

    A plain mapping rather than an object, because a case must stay JSON-serializable: its contents
    go into the dataset's checksum, which is what makes a run reproducible.
    """

    expected = case.expected
    if not isinstance(expected, Mapping):
        return None
    reference = expected.get(CASE_KEY)
    return reference if isinstance(reference, Mapping) else None


def _figures_from_output(output: Any) -> Mapping[str, Any]:
    """Figures the agent returned as data, under `PredictionResult.extra["figures"]`.

    Reading a number out of prose is guesswork, however careful. An agent that can hand back its
    figures should, and then this is exact.
    """

    extra = getattr(output, "extra", None)
    if not isinstance(extra, Mapping):
        return {}
    figures = extra.get(FIGURES_KEY)
    return figures if isinstance(figures, Mapping) else {}


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


@dataclass(frozen=True, slots=True)
class FieldVerdict:
    """What happened to one field, in terms a reader can act on."""

    expected: float
    claimed: float | None
    matched: bool | None  # None when the answer never stated it
    difference: float | None = None
    note: str | None = None

    def record(self) -> dict[str, Any]:
        recorded: dict[str, Any] = {"expected": self.expected, "claimed": self.claimed, "matched": self.matched}
        if self.difference is not None:
            recorded["difference"] = self.difference
        if self.note:
            recorded["note"] = self.note
        return recorded


@dataclass(frozen=True, slots=True)
class SqlReference:
    """Scores an answer's figures against the rows a case's own query returns.

    `tolerances` sets how close each field must be, falling back to `default_tolerance`. Name a field
    in `fraction_fields` when the table stores it as a fraction and the answer is likely to write it
    as a percentage, so "0.42%" is read as 0.0042 rather than compared as 0.42.
    """

    execute: SqlExecutor
    tolerances: Mapping[str, Tolerance] = field(default_factory=dict)
    default_tolerance: Tolerance = Tolerance("relative", 0.01)
    fraction_fields: Sequence[str] = ()
    query_of: Callable[[EvaluationCase], Mapping[str, Any] | None] = _query_from_case
    figures_of: Callable[[Any], Mapping[str, Any]] = _figures_from_output
    window: int = DEFAULT_WINDOW
    name: str = "figures"

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult:
        truth = await self.ground_truth(case)
        if isinstance(truth, Unmeasured):
            return MultiScoreResult(
                {f"{self.name}.measured": 0.0},
                {f"{self.name}.measured": {"unmeasured": truth.reason}},
            )
        row, fields, required = truth
        # Resolved together, so a field cannot take the figure sitting next to another field's name.
        stated_numbers = numbers_by_label(str(answer_of(output)), list(fields.values()), window=self.window)
        verdicts = {
            name: self._verdict(name, row[name], stated_numbers.get(label), output)
            for name, label in fields.items()
        }

        stated = {name: verdict for name, verdict in verdicts.items() if verdict.matched is not None}
        missing = sorted(name for name in required if verdicts[name].matched is None)

        scores: dict[str, float] = {f"{self.name}.measured": 1.0}
        details: dict[str, Mapping[str, Any]] = {
            f"{self.name}.measured": {"fields": {name: verdict.record() for name, verdict in verdicts.items()}}
        }
        if stated:
            scores[self.name] = sum(1.0 for verdict in stated.values() if verdict.matched) / len(stated)
            details[self.name] = {
                "disagreed": {
                    name: verdict.record() for name, verdict in stated.items() if verdict.matched is False
                }
            }
        if required:
            scores[f"{self.name}.coverage"] = 1.0 - len(missing) / len(required)
            details[f"{self.name}.coverage"] = {"never_stated": missing}
        return MultiScoreResult(scores, details)

    async def ground_truth(
        self, case: EvaluationCase
    ) -> tuple[Mapping[str, Any], Mapping[str, str], Sequence[str]] | Unmeasured:
        """The one row the case's query returns, or why it could not be had.

        Every refusal is named. More than one row is refused rather than taking the first: which row
        was meant is a question only the case author can answer, and picking silently would compare
        against an arbitrary one.
        """

        declared = self.query_of(case)
        if not declared or not declared.get("sql"):
            return Unmeasured("the case declares no reference query")
        fields = _declared_fields(declared)
        if not fields:
            return Unmeasured("the case's reference names no fields to check")
        try:
            rows = await self.execute(str(declared["sql"]), dict(declared.get("parameters") or {}))
        except Exception as error:  # noqa: BLE001 -- a database that is down is not the agent's fault
            return Unmeasured(f"the reference query failed: {type(error).__name__}: {error}")
        if not rows:
            return Unmeasured("the reference query returned no rows")
        if len(rows) > 1:
            return Unmeasured(f"the reference query returned {len(rows)} rows; it must return one")
        row = rows[0]
        absent = sorted(name for name in fields if name not in row)
        if absent:
            return Unmeasured(f"the reference query returned no column for {', '.join(absent)}")
        unusable = sorted(name for name in fields if _as_number(row[name]) is None)
        if unusable:
            return Unmeasured(f"the reference value for {', '.join(unusable)} is not a finite number")
        required = [name for name in (declared.get("required") or fields) if name in fields]
        return {name: _as_number(row[name]) for name in fields}, fields, required

    def _verdict(self, field_name: str, expected: float, stated: StatedNumber | None, output: Any) -> FieldVerdict:
        structured = _as_number(self.figures_of(output).get(field_name))
        if structured is not None:
            return self._compare(field_name, expected, structured, abbreviated=False, note=None)
        if stated is None:
            return FieldVerdict(expected=expected, claimed=None, matched=None)
        claimed, note = self._read(field_name, stated)
        return self._compare(field_name, expected, claimed, abbreviated=stated.abbreviated, note=note)

    def _read(self, field_name: str, stated: StatedNumber) -> tuple[float, str | None]:
        """A stated figure as a number comparable to the table's, and anything odd about how it was written."""

        if stated.percent and field_name in self.fraction_fields:
            return stated.value / 100, "the answer wrote a percentage and the table stores a fraction"
        if stated.percent:
            return stated.value, "the answer wrote a percent sign; compared as written"
        return stated.value, None

    def _compare(
        self, field_name: str, expected: float, claimed: float, *, abbreviated: bool, note: str | None
    ) -> FieldVerdict:
        tolerance = self.tolerances.get(field_name, self.default_tolerance)
        widen = abbreviated and tolerance.kind == "relative"
        matched = tolerance.matches(claimed, expected, abbreviated=widen)
        return FieldVerdict(
            expected=expected,
            claimed=claimed,
            matched=matched,
            difference=None if matched else claimed - expected,
            note=note,
        )


def _declared_fields(declared: Mapping[str, Any]) -> dict[str, str]:
    """The fields to check, as `column -> the word to look for in the answer`.

    A list means the column name is also the label, which is the common case.
    """

    fields = declared.get("fields")
    if isinstance(fields, Mapping):
        return {str(name): str(label) for name, label in fields.items()}
    if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
        return {str(name): str(name) for name in fields}
    return {}


class _SharedProbe:
    """Runs one `SqlReference` once per answer and lets two criteria read the same result.

    A rubric awaits its criteria one after another on the same `(case, output)`, so a single-entry
    memo is enough and the query runs once rather than per criterion. Without this, feeding both the
    figures and the coverage criteria would double every warehouse query in a run.
    """

    def __init__(self, reference: SqlReference) -> None:
        self._reference = reference
        self._case_id: str | None = None
        # Held, not just identified. CPython reuses the address of a freed object, so caching on
        # id() alone handed the next answer the previous one's scores: every case in a run came back
        # with the first case's figures. Keeping the object alive makes its id unique while cached.
        self._output: Any = None
        self._result: MultiScoreResult | None = None

    async def result(self, case: EvaluationCase, output: Any) -> MultiScoreResult:
        if self._result is None or self._case_id != case.case_id or self._output is not output:
            self._case_id, self._output = case.case_id, output
            self._result = await self._reference(case, output)
        return self._result

    def reading(self, metric: str) -> Callable[[EvaluationCase, Any], Any]:
        async def criterion(case: EvaluationCase, output: Any) -> Any:
            result = await self.result(case, output)
            if metric not in result.scores:
                reason = result.details.get(f"{self._reference.name}.measured", {}).get("unmeasured")
                return Unmeasured(reason) if reason else None
            detail = result.details.get(metric)
            return MultiScoreResult({metric: result.scores[metric]}, {metric: detail} if detail else {})

        return criterion


def reference_criteria(reference: SqlReference, *, figures: str = "figures", coverage: str = "completeness") -> dict:
    """Two rubric criteria over one query: whether the stated figures are right, and whether they were stated.

    Pass the result into `AnswerRubric(criteria=...)`. Name them to match your rubric's weights; the
    coverage one is a floor for completeness rather than the whole of it, since a model judge sees
    things a column list cannot.
    """

    probe = _SharedProbe(reference)
    return {figures: probe.reading(reference.name), coverage: probe.reading(f"{reference.name}.coverage")}
