"""Questions whose correct answer is "that cannot be answered from this data".

Some questions have no answer, and saying so is the right one. Of 50 hand-reviewed rubrics for one
agent's real traffic, 10 carry an `acceptable_non_answer` — a request for the top 30 apps by
impressions against a table with no app dimension, a request for one inventory source against a
table that cannot identify it. 7 of those 50 have no checkable metric at all.

Scoring those questions the ordinary way does not merely miss something. It inverts the verdict: the
reference query returns campaign totals, the answer correctly states that app-level data does not
exist, and the agent is marked wrong **for being right**. That is worse than not measuring, because
it is wrong with a number attached.

Two pieces, kept apart because they answer different questions.

`AcceptedRefusal` scores the refusal itself, and it is not a free pass. A case that accepts a
refusal and gets one scores 1.0; one that accepts a refusal and gets a confident answer instead
scores **0.0**, because an agent that produced a top-30 app list from a table with no app column
invented it. That second case is the one worth catching, and nothing else in the library would.

`WhenNotRefused` wraps any other criterion so it does not apply to an answer that correctly
declined. Wrapping rather than teaching each criterion about refusals: `SqlReference` has no
business knowing what a refusal is, and a project with its own criterion gets the same treatment
without changing it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..core.evaluation import EvaluationCase, _await_value
from ..core.prediction import MultiScoreResult, Unmeasured
from .outcome import answer_of

CASE_KEY = "acceptable_non_answer"

RefusalCheck = Callable[[EvaluationCase, Any], bool | Awaitable[bool]]
"""Whether this answer declined to answer.

Reading an answer is a judgement, so this is a seam rather than a rule. There is no text-matching
default: "the delivery dataset has no app dimension" and "I can't break that out by app" are the
same refusal and share no words, and a keyword list that got it wrong would silently hand back the
inverted verdict this module exists to prevent.
"""


def _accepted_from_case(case: EvaluationCase) -> str:
    """What the case says an acceptable refusal would state, or "" when it accepts none.

    Text rather than a boolean, because a refusal has to be the *right* refusal. "There is no app
    dimension in this data" and "I don't know" are both non-answers and only one of them is correct,
    so whatever decides that needs the description, not a flag.
    """

    expected = case.expected
    if not isinstance(expected, Mapping):
        return ""
    declared = expected.get(CASE_KEY)
    return str(declared).strip() if isinstance(declared, str) else ""


@dataclass(frozen=True, slots=True)
class AcceptedRefusal:
    """Scores whether an answer declined on a question where declining was correct.

    `refused` decides whether this answer is a refusal; the case decides whether one was acceptable.
    Keeping those apart is the point: the agent never gets to say whether its own non-answer was the
    right call.
    """

    refused: RefusalCheck
    accepted_of: Callable[[EvaluationCase], str] = _accepted_from_case
    name: str = "refusal"

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult | Unmeasured | None:
        accepted = self.accepted_of(case)
        if not accepted:
            # The question has a real answer, so declining is not on the table and this criterion
            # has nothing to say. Not zero: an answer is not wrong for failing to refuse.
            return None

        if not str(answer_of(output)).strip():
            # An empty answer is not a refusal. A refusal states what cannot be done and why, which
            # is the thing the rubric accepts; silence is a failure that happens to look like one.
            return MultiScoreResult({self.name: 0.0}, {self.name: {"accepted": accepted, "answer": "empty"}})

        try:
            declined = bool(await _await_value(self.refused(case, output)))
        except Exception as error:  # noqa: BLE001 -- a check that broke read nothing
            return Unmeasured(f"whether the answer declined could not be decided: {type(error).__name__}: {error}")

        if declined:
            return MultiScoreResult({self.name: 1.0}, {self.name: {"accepted": accepted, "declined": True}})
        # It answered a question whose data does not exist. Whatever figures it gave came from
        # somewhere other than the source, which is the fabrication case this criterion is for.
        return MultiScoreResult(
            {self.name: 0.0},
            {
                self.name: {
                    "accepted": accepted,
                    "declined": False,
                    "note": "answered a question the data cannot answer",
                }
            },
        )


@dataclass(frozen=True, slots=True)
class WhenNotRefused:
    """Wraps a criterion so it does not apply to an answer that correctly declined.

    Returns `None` — does not apply — rather than a score, so `score_rubric` drops the criterion
    from the denominator instead of averaging in a zero the answer did not earn.
    """

    criterion: Callable[[EvaluationCase, Any], Any]
    refused: RefusalCheck
    accepted_of: Callable[[EvaluationCase], str] = _accepted_from_case

    async def __call__(self, case: EvaluationCase, output: Any) -> Any:
        if not self.accepted_of(case):
            # Declining was never acceptable here, so there is nothing to make way for.
            return await _await_value(self.criterion(case, output))
        try:
            declined = bool(await _await_value(self.refused(case, output)))
        except Exception as error:  # noqa: BLE001 -- unable to tell whether this criterion applies
            # Scoring anyway is the inverted verdict this module exists to prevent: on these
            # questions the reference disagrees with a correct refusal by design, so a check that
            # could not run must withhold rather than fall through.
            return Unmeasured(
                f"whether this criterion applies could not be decided: {type(error).__name__}: {error}"
            )
        if declined:
            return None
        return await _await_value(self.criterion(case, output))


__all__ = ["CASE_KEY", "AcceptedRefusal", "RefusalCheck", "WhenNotRefused"]
