"""Whether an answer is about the thing the question asked about.

The cheapest criterion to check and, on real traffic, the one that catches most. One recorded
baseline had nine of its eleven failures turn on scope alone: the figures were right, and they were
the right figures for the wrong campaign.

The entity comes from the case, never from the agent. Taking it from the agent's own call would be
asking the thing under test what it was supposed to be doing, and a wrong answer would then agree
with itself. That is not a hypothetical: the one existing attempt at automated ground truth in the
campaign repository reads its filters off the agent's answering call, and the comparison it enabled
was removed for being circular.

This reads text, so it is bounded. It can tell that an answer discusses 109778 when 109249 was
asked about. It cannot tell that an answer naming the right campaign fetched the wrong one; that
needs the agent's own tool arguments, and is a separate check.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.evaluation import EvaluationCase
from ..core.prediction import MultiScoreResult, Unmeasured
from .claims import _mentions
from .outcome import answer_of

CASE_KEY = "scope"


def _scope_from_case(case: EvaluationCase) -> Mapping[str, Any] | None:
    """What the question is about, from `expected["scope"]`.

    A plain mapping, because a case has to stay JSON-serializable: its contents go into the
    dataset's checksum, and that checksum is what makes a run reproducible.
    """

    expected = case.expected
    if not isinstance(expected, Mapping):
        return None
    declared = expected.get(CASE_KEY)
    return declared if isinstance(declared, Mapping) else None


@dataclass(frozen=True, slots=True)
class EntityScope:
    """Scores whether the answer names the entity the case says the question was about.

    `pattern` in the case's scope block is what makes the negative case possible: without a way to
    recognise another entity of the same kind, an answer about the wrong campaign is indistinguishable
    from an answer that simply did not repeat the id.
    """

    scope_of: Callable[[EvaluationCase], Mapping[str, Any] | None] = _scope_from_case
    name: str = "scope"

    def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult | Unmeasured:
        declared = self.scope_of(case)
        if not declared or not str(declared.get("entity", "")).strip():
            return Unmeasured("the case declares no entity, so there is nothing to check scope against")

        entity = str(declared["entity"]).strip()
        wanted = [entity, *(str(alias) for alias in declared.get("aliases") or ())]
        answer = str(answer_of(output))

        named = [name for name in wanted if _mentions(answer, name)]
        others = _others(answer, declared.get("pattern"), wanted)

        if named:
            return MultiScoreResult(
                {self.name: 1.0},
                {self.name: {"named": named, "also_named": others}} if others else {},
            )
        if others:
            return MultiScoreResult(
                {self.name: 0.0},
                {self.name: {"expected": entity, "answered_about": others}},
            )
        return Unmeasured(f"the answer names no entity, so it cannot be told whether it is about {entity}")


def _others(answer: str, pattern: Any, wanted: Sequence[str]) -> list[str]:
    """Entities of the same kind that the answer names and the question did not ask about.

    Needs the pattern: "109778" is only recognisable as another campaign id because the case said
    what a campaign id looks like. Without one this stays empty, and the criterion can report that
    the right entity was named but never that a wrong one was.
    """

    if not isinstance(pattern, str) or not pattern:
        return []
    try:
        found = re.findall(pattern, answer)
    except re.error:
        return []
    expected = {name.casefold() for name in wanted}
    others: dict[str, str] = {}
    for match in found:
        # A pattern with a capture group yields tuples; take the whole match's first non-empty part.
        text = match if isinstance(match, str) else next((part for part in match if part), "")
        if text and text.casefold() not in expected:
            others.setdefault(text.casefold(), text)
    return list(others.values())


__all__ = ["CASE_KEY", "EntityScope"]
