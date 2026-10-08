"""Whether an answer said what it could not tell you.

The most common requirement nothing in this library checked. Of 50 hand-reviewed rubrics for one
agent's real traffic, 23 require a `caveat_or_data_gap` — the answer must state that reach is
unavailable for this campaign, that the week is still in flight, that the table has no app
dimension. An answer that quietly omits the caveat reads as complete and is not.

It is scored like grounding and for the same reason: **only positive evidence counts**. An answer
earns this by stating the limitation. Silence earns nothing — not a pass, because nothing was
established, and not a failure either, because a check that looked and found no mention cannot tell
"the answer omitted the caveat" from "my reader missed it". So a case that requires a gap and gets
no evidence of one scores 0.0, while a case that requires none does not apply at all. The asymmetry
is deliberate: the requirement comes from the case, so its absence is known, and only then is a
missing caveat a verdict rather than a guess.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.evaluation import EvaluationCase, _await_value
from ..core.prediction import MultiScoreResult, Unmeasured
from .outcome import answer_of

CASE_KEY = "data_gaps"

GapCheck = Callable[[EvaluationCase, Any, str], bool | Awaitable[bool]]
"""Whether the answer states one named limitation.

Per gap rather than all at once, so a partially caveated answer scores partially. There is no
text-matching default: "reach is not available for this campaign" and "we don't have reach here"
share almost no words, and a keyword list that missed one would report a correct answer as silent.
"""


def _gaps_from_case(case: EvaluationCase) -> tuple[str, ...]:
    """The limitations this question's answer has to state, from `expected["data_gaps"]`.

    Plain strings, because a case has to stay JSON-serializable: its contents go into the dataset's
    checksum, and that checksum is what makes a run reproducible.
    """

    expected = case.expected
    if not isinstance(expected, Mapping):
        return ()
    declared = expected.get(CASE_KEY)
    if isinstance(declared, str):
        return (declared,) if declared.strip() else ()
    if isinstance(declared, Sequence):
        return tuple(str(gap).strip() for gap in declared if str(gap).strip())
    return ()


@dataclass(frozen=True, slots=True)
class DataGapStated:
    """Scores how many of the limitations a question runs into the answer actually stated.

    `states` decides whether one named gap is mentioned; the case decides which gaps are required.
    The agent never contributes to the list, because an agent that omitted a caveat would otherwise
    be asked whether a caveat was needed.
    """

    states: GapCheck
    gaps_of: Callable[[EvaluationCase], Sequence[str]] = _gaps_from_case
    name: str = "data_gap"

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult | Unmeasured | None:
        required = tuple(self.gaps_of(case))
        if not required:
            # This question runs into no limitation worth stating, so there is nothing to caveat.
            return None

        answer = str(answer_of(output)).strip()
        if not answer:
            return MultiScoreResult({self.name: 0.0}, {self.name: {"required": list(required), "answer": "empty"}})

        stated: list[str] = []
        for gap in required:
            try:
                mentioned = bool(await _await_value(self.states(case, output, gap)))
            except Exception as error:  # noqa: BLE001 -- a reader that broke found nothing
                # Not 0.0. A reader that failed is a verdict about the reader, and scoring the
                # answer on it would call a caveated answer silent.
                return Unmeasured(
                    f"whether the answer stated its limitations could not be read: {type(error).__name__}: {error}"
                )
            if mentioned:
                stated.append(gap)

        missing = [gap for gap in required if gap not in stated]
        return MultiScoreResult(
            {self.name: len(stated) / len(required)},
            {self.name: {"stated": stated, "missing": missing}},
        )


__all__ = ["CASE_KEY", "DataGapStated", "GapCheck"]
