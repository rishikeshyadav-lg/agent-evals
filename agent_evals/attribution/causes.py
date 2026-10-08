"""One dominant cause per bad run, by first match over an ordered list of rules.

Ordered rather than scored. A wrong figure that came from an empty tool result is one failure with
one fix, and reporting both as findings makes the reader choose between them.

The order is **causal, not severity-ranked**: a cause sits above every cause it can produce. Wrong
scope outranks wrong figures because right numbers about the wrong campaign are wrong numbers, and
fixing the scope fixes both. A failed run outranks "called no tools" because a run that never
finished has no tool calls for reasons that are not the agent's choice.

Nothing here asserts a cause from the absence of a signal. A rule that cannot establish its cause
returns None — the same way `Unmeasured` means "could not measure" rather than "zero" — and a bad
run that nothing explains comes back unattributable with the reason instead of a guess.

`Attribution.also` carries every other rule that matched, so the precedence order stops being
load-bearing: the headline names one cause and nothing is lost.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from ..running.execution import RepeatedRun
from .facts import EmptyResult, RunFacts, declared_empty, facts_of_row

RUBRIC = "accuracy"

CauseCode = Literal[
    "run_failed",
    "measurement_unavailable",
    "no_answer",
    "no_tool_calls",
    "tool_error",
    "fabricated_from_empty_result",
    "empty_tool_result",
    "failure_code",
    "wrong_scope",
    "figures_wrong",
    "breakdown_missing",
    "breakdown_figures_wrong",
    "breakdown_incomplete",
    "incomplete",
    "interpretation_unsupported",
]


@dataclass(frozen=True, slots=True)
class Cause:
    """One reason a run went wrong, with the values that establish it.

    `evidence` is what the cause was read from, not a restatement of `detail`: the claim has to be
    checkable without rerunning anything, because the first thing anyone does with an attributed
    cause is disbelieve it. `blames_agent` is False only for a cause that is a gap in our own
    measurement, which must never be counted against the thing under test.
    """

    code: CauseCode
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    blames_agent: bool = True
    experimental: bool = False

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError(f"the cause {self.code!r} needs a detail saying what it means")


@dataclass(frozen=True, slots=True)
class Attribution:
    """The dominant cause of one run going wrong, the runners-up, and what nobody could look at.

    `cause` is None in two unrelated situations and `attributable` tells them apart: the run scored
    well and there is nothing to explain, or it scored badly and nothing observed explains it.
    Reporting the second as "no cause" reads as a clean bill of health for the case that most needs
    one.
    """

    case_id: str
    variant_id: str
    repeat: int
    cause: Cause | None
    also: Sequence[Cause] = ()
    attributable: bool = True
    reason: str | None = None
    unmeasured: Mapping[str, str] = field(default_factory=dict)

    @property
    def code(self) -> CauseCode | None:
        return self.cause.code if self.cause is not None else None


@runtime_checkable
class CauseRule(Protocol):
    """One candidate cause, asked of one run's facts.

    Returns its cause when the facts establish it, and None both when they establish the opposite
    and when they establish nothing. Those two are the same answer here on purpose: the ordering
    decides which established cause wins, so a rule that guessed would outrank a rule that knew.
    """

    @property
    def code(self) -> CauseCode:
        """The code this rule reports, so a caller can name the rules it replaced."""

    def __call__(self, facts: RunFacts) -> Cause | None: ...


@dataclass(frozen=True, slots=True)
class RunFailed:
    """The run never finished, so there is no answer to diagnose.

    Above everything but our own measurement, because a timed-out run also has no tool calls and no
    answer, and every rule below would describe that silence as a choice the agent made.
    """

    code: CauseCode = "run_failed"

    def __call__(self, facts: RunFacts) -> Cause | None:
        if not facts.run_error:
            return None
        return Cause(
            code=self.code,
            detail="the run did not finish, so there is no answer to diagnose",
            evidence={"error": facts.run_error},
        )


@dataclass(frozen=True, slots=True)
class MeasurementUnavailable:
    """Our own measurement did not run, so nothing here is the agent's fault — with one exception.

    It yields when something else *was* measured and failed outright. A judge that was down while
    the figures were checked and disagreed is a partial diagnosis, not an acquittal, so the real
    finding wins and the unmeasured criteria travel on `Attribution.unmeasured` instead.
    """

    rubric: str = RUBRIC
    yields_to: Sequence[str] = ("scope", "figures", "completeness", "breakdown.rows", "breakdown.figures")
    code: CauseCode = "measurement_unavailable"

    def __call__(self, facts: RunFacts) -> Cause | None:
        unmeasured = _unmeasured(facts, self.rubric)
        if not unmeasured:
            return None
        for criterion in self.yields_to:
            score = facts.metric(f"{self.rubric}.{criterion}", criterion)
            if score is not None and score < 1.0:
                return None
        return Cause(
            code=self.code,
            detail="our own measurement did not run, so this run's score is not the agent's fault",
            evidence={"unmeasured": dict(unmeasured)},
            blames_agent=False,
        )


@dataclass(frozen=True, slots=True)
class NoAnswer:
    """The run completed and said nothing. Distinct from a wrong answer and from a failed run."""

    code: CauseCode = "no_answer"

    def __call__(self, facts: RunFacts) -> Cause | None:
        if facts.answer is None or not str(facts.answer).strip():
            return Cause(code=self.code, detail="the run finished and produced no answer")
        return None


@dataclass(frozen=True, slots=True)
class NoToolCalls:
    """The agent answered without fetching anything — and only when the record proves it had the chance.

    A row whose runner returned no trajectory looks identical to one that called nothing, so this
    fires only on `calls_known`. Without it the cause would be asserted from the shape of the
    runner, which is the one thing this module refuses to do.
    """

    code: CauseCode = "no_tool_calls"

    def __call__(self, facts: RunFacts) -> Cause | None:
        if facts.calls or facts.calls_known is not True:
            return None
        return Cause(
            code=self.code,
            detail="the agent answered without calling any tool, so nothing it said came from the source",
            evidence={"calls_known": True},
        )


@dataclass(frozen=True, slots=True)
class ToolErrored:
    """A tool call failed.

    From a recorded row this can name the tool and the index and not the message, because
    `_tool_calls` keeps a status and drops `step.error` and `step.failure`.
    """

    code: CauseCode = "tool_error"

    def __call__(self, facts: RunFacts) -> Cause | None:
        failed = [call for call in facts.calls if call.errored]
        if not failed:
            return None
        return Cause(
            code=self.code,
            detail="a tool call failed, so the answer was built on an incomplete fetch",
            evidence={"tools": [{"index": c.index, "tool": c.tool, "error": c.error} for c in failed]},
        )


@dataclass(frozen=True, slots=True)
class EmptyToolResult:
    """A tool returned no rows — and, separately, whether the answer nonetheless stated a figure.

    Seven of 56 runs in one recorded baseline stated confident figures while their tools came back
    with `row_count=0`. That is fabrication and gets its own code. An agent that correctly reports
    there was no data has the same empty result and is not wrong, so the stronger code needs the
    stronger evidence: `SqlReference` reports a `figures` score **only** when the answer stated one,
    which makes the metric's presence proof enough and its absence no proof at all.
    """

    rubric: str = RUBRIC
    figure_metrics: Sequence[str] = ("figures", "breakdown.figures")
    code: CauseCode = "fabricated_from_empty_result"
    fallback_code: CauseCode = "empty_tool_result"

    def __call__(self, facts: RunFacts) -> Cause | None:
        # Only when every call that said anything said empty. One call that returned rows means the
        # answer had a source to read, and a call that said nothing either way is not evidence.
        spoke = [call for call in facts.calls if call.empty is not None]
        empty = [call for call in spoke if call.empty]
        if not empty or len(empty) != len(spoke):
            return None
        evidence = {"tools": [{"index": c.index, "tool": c.tool, "row_count": c.row_count} for c in empty]}
        stated = any(
            facts.metric(f"{self.rubric}.{name}", name) is not None for name in self.figure_metrics
        )
        if stated:
            return Cause(
                code=self.code,
                detail="every tool returned no rows and the answer still stated figures, so they were invented",
                evidence=evidence,
            )
        return Cause(
            code=self.fallback_code,
            detail="every tool returned no rows, so there was nothing for the answer to report",
            evidence=evidence,
        )


@dataclass(frozen=True, slots=True)
class RubricFailureCode:
    """The rubric already decided this answer failed, and said why.

    Its own verdict outranks any score this module could read: `AnswerRubric` zeroes the headline on
    a failure code and keeps the weighted score only as a diagnosis, so a score-derived cause below
    would be describing a number the rubric had already overruled.
    """

    rubric: str = RUBRIC
    code: CauseCode = "failure_code"

    def __call__(self, facts: RunFacts) -> Cause | None:
        codes: list[str] = []
        for name in (self.rubric, f"{self.rubric}.measured"):
            found = facts.score_details.get(name)
            if isinstance(found, Mapping):
                raw = found.get("failure_codes")
                if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                    codes.extend(str(code) for code in raw)
        unique = sorted(set(codes))
        if not unique:
            return None
        return Cause(
            code=self.code,
            detail=f"the rubric failed this answer outright: {', '.join(unique)}",
            evidence={"failure_codes": unique},
        )


@dataclass(frozen=True, slots=True)
class CriterionBelow:
    """One named criterion scoring under its bar, as one cause.

    The rule the six domain causes are instances of. Scope, figures, the two breakdown halves,
    completeness and interpretation differ only in which metric they read and what the number means,
    so a project with a seventh criterion gets its cause without this module learning the name.
    """

    criterion: str
    code: CauseCode
    detail: str
    below: float = 1.0
    at_most: float | None = None
    at_least: float | None = None
    rubric: str = RUBRIC
    evidence_keys: Sequence[str] = ()
    experimental: bool = False

    def __call__(self, facts: RunFacts) -> Cause | None:
        prefixed = f"{self.rubric}.{self.criterion}"
        score = facts.metric(prefixed, self.criterion)
        if score is None or score >= self.below:
            return None
        if self.at_most is not None and score > self.at_most:
            return None
        if self.at_least is not None and score <= self.at_least:
            return None
        detail = facts.detail(prefixed, self.criterion)
        evidence: dict[str, Any] = {"score": score}
        for key in self.evidence_keys:
            if key in detail:
                evidence[key] = detail[key]
        return Cause(code=self.code, detail=self.detail, evidence=evidence, experimental=self.experimental)


DEFAULT_RULES: tuple[CauseRule, ...] = (
    RunFailed(),
    MeasurementUnavailable(),
    NoAnswer(),
    NoToolCalls(),
    ToolErrored(),
    EmptyToolResult(),
    RubricFailureCode(),
    CriterionBelow(
        "scope",
        "wrong_scope",
        "the answer is about a different entity than the question asked about",
        at_most=0.0,
        evidence_keys=("expected", "answered_about"),
    ),
    CriterionBelow(
        "figures",
        "figures_wrong",
        "the tools returned data and the stated figures still disagree with the reference",
        evidence_keys=("disagreed",),
    ),
    CriterionBelow(
        "breakdown.rows",
        "breakdown_missing",
        "the question asked for a per-key table and the answer gave none of its keys",
        at_most=0.0,
        evidence_keys=("expected_keys",),
    ),
    CriterionBelow(
        "breakdown.figures",
        "breakdown_figures_wrong",
        "the table was given and its numbers disagree with the reference",
        evidence_keys=("disagreed",),
    ),
    CriterionBelow(
        "breakdown.rows",
        "breakdown_incomplete",
        "the table was given and some of its keys are missing",
        at_least=0.0,
        evidence_keys=("missing_keys",),
    ),
    CriterionBelow(
        "completeness",
        "incomplete",
        "the answer left out something the question asked for",
        evidence_keys=("omission", "coverage"),
    ),
    CriterionBelow(
        "interpretation",
        "interpretation_unsupported",
        "the answer's conclusions do not follow from the data it showed",
        experimental=True,
    ),
)


def _unmeasured(facts: RunFacts, rubric: str) -> Mapping[str, str]:
    """The criteria the rubric could not measure, as `criterion -> why`."""

    detail = facts.score_details.get(f"{rubric}.measured")
    if not isinstance(detail, Mapping):
        return {}
    found = detail.get("unmeasured")
    if not isinstance(found, Mapping):
        return {}
    return {str(name): str(reason) for name, reason in found.items()}


def attribute(
    facts: RunFacts,
    *,
    rules: Sequence[CauseRule] = DEFAULT_RULES,
    success_metric: str = RUBRIC,
    passing_at: float = 1.0,
) -> Attribution:
    """The one dominant cause of this run going wrong, or an honest statement that there is none.

    A run scoring `passing_at` or better on `success_metric` gets `cause=None, attributable=True`:
    there is nothing to explain and saying so is the answer. A run with no `success_metric` at all is
    **not** treated as good — that is exactly the case the rubric withheld a headline from, and it
    goes on to be attributed, usually to `measurement_unavailable`.
    """

    unmeasured = _unmeasured(facts, success_metric)
    headline = facts.metric(success_metric)
    if headline is not None and headline >= passing_at:
        return Attribution(
            case_id=facts.case_id,
            variant_id=facts.variant_id,
            repeat=facts.repeat,
            cause=None,
            attributable=True,
            reason=f"the run scored {headline:.3f} on {success_metric}",
            unmeasured=unmeasured,
        )

    matched = [cause for cause in (rule(facts) for rule in rules) if cause is not None]
    if not matched:
        return Attribution(
            case_id=facts.case_id,
            variant_id=facts.variant_id,
            repeat=facts.repeat,
            cause=None,
            attributable=False,
            reason="the run scored badly and nothing recorded explains it",
            unmeasured=unmeasured,
        )
    return Attribution(
        case_id=facts.case_id,
        variant_id=facts.variant_id,
        repeat=facts.repeat,
        cause=matched[0],
        also=tuple(matched[1:]),
        attributable=True,
        unmeasured=unmeasured,
    )


def attribute_run(
    run: RepeatedRun,
    variant_id: str,
    *,
    rules: Sequence[CauseRule] = DEFAULT_RULES,
    success_metric: str = RUBRIC,
    passing_at: float = 1.0,
    empty_result: EmptyResult = declared_empty,
) -> tuple[Attribution, ...]:
    """Attribute every row of one variant, in the run's own order."""

    return tuple(
        attribute(
            facts_of_row(row, empty_result=empty_result),
            rules=rules,
            success_metric=success_metric,
            passing_at=passing_at,
        )
        for row in run.rows
        if row.variant_id == variant_id
    )


__all__ = [
    "DEFAULT_RULES",
    "RUBRIC",
    "Attribution",
    "Cause",
    "CauseCode",
    "CauseRule",
    "CriterionBelow",
    "EmptyToolResult",
    "MeasurementUnavailable",
    "NoAnswer",
    "NoToolCalls",
    "RubricFailureCode",
    "RunFailed",
    "ToolErrored",
    "attribute",
    "attribute_run",
]
