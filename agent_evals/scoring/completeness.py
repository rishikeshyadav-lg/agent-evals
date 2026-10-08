"""Whether the answer covered what was asked.

Two halves, because the question has two halves. Some of what is asked for is countable — four
metrics were wanted and three were given — and a query settles that exactly. The rest is not: a
question asking for notable trends is answered or it is not, and only something that reads the
answer can say which.

So this combines a deterministic coverage score with an optional check that can report an omission.
The asymmetry matters and is deliberate: the reading check can only *lower* the score. It looked and
found nothing missing, which is not the same as having established that the answer was complete —
the same reason grounding is a failure code and never a number.

Routing is the caller's. A project whose omission check already fails the case through
`failure_codes_of` leaves `omission_of` unset and nothing is counted twice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..core.evaluation import EvaluationCase, _await_value
from ..core.prediction import MultiScoreResult, Unmeasured, normalize_scores

OmissionCheck = Callable[[EvaluationCase, Any], bool | Awaitable[bool]]
"""True when something the question asked for is missing from the answer."""


@dataclass(frozen=True, slots=True)
class Completeness:
    """Rolls a countable coverage score and a reading check into one criterion.

    `coverage` is any criterion reporting a fraction — `reference_criteria`'s coverage half is the
    obvious one. `omission_of` is anything that can say a specific requested thing is missing.
    """

    coverage: Callable[[EvaluationCase, Any], Any] | None = None
    omission_of: OmissionCheck | None = None
    name: str = "completeness"

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult | Unmeasured | None:
        fraction, coverage_reason = await self._coverage(case, output)
        omitted, omission_reason = await self._omission(case, output)

        if omitted:
            # Whatever the figures showed, something asked for is not there. A question wanting
            # trends is not three-quarters answered because three of four numbers were right.
            detail: dict[str, Any] = {"omission": True}
            if fraction is not None:
                detail["coverage"] = fraction
            return MultiScoreResult({self.name: 0.0}, {self.name: detail})

        if omission_reason:
            # A configured check that could not run leaves half the question unanswered. Reporting
            # the coverage fraction alone would say completeness was assessed when only the
            # countable half was -- the same flattering reading grounding already refuses.
            return Unmeasured(omission_reason)

        if fraction is not None:
            return MultiScoreResult({self.name: fraction}, {self.name: {"coverage": fraction}})

        # Nothing countable, and a reading check that found nothing missing is not evidence that
        # nothing is missing. Reporting 1.0 here would be completeness claimed from silence.
        return Unmeasured(coverage_reason or omission_reason or "nothing established what the answer had to cover")

    async def _coverage(self, case: EvaluationCase, output: Any) -> tuple[float | None, str]:
        if self.coverage is None:
            return None, ""
        try:
            value = await _await_value(self.coverage(case, output))
        except Exception as error:  # noqa: BLE001 -- a coverage scorer that broke has no verdict
            return None, f"the coverage check raised: {type(error).__name__}: {error}"
        if isinstance(value, Unmeasured):
            return None, value.reason
        if value is None:
            return None, "the question required no countable thing"
        scores, _ = normalize_scores(value, scorer=self.name)
        return next(iter(scores.values()), None), ""

    async def _omission(self, case: EvaluationCase, output: Any) -> tuple[bool, str]:
        if self.omission_of is None:
            return False, ""
        try:
            return bool(await _await_value(self.omission_of(case, output))), ""
        except Exception as error:  # noqa: BLE001 -- a check that broke found nothing, and says so
            return False, f"the omission check raised: {type(error).__name__}: {error}"


__all__ = ["Completeness", "OmissionCheck"]
