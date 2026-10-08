"""Asking a model whether an answer's conclusions follow from its data.

The last criterion of accuracy and the only one that cannot be settled by arithmetic. Whether a
trend is notable, or a recommendation supported, has no deterministic answer — so this asks a model,
and then treats the result with the suspicion that deserves.

It is built to be reported beside a headline rather than inside one. Pass it to `AnswerRubric` as
`reported_only` and the number people act on does not move when the judge does. Promoting it into
the weights is a decision to make after `validate_judge` has measured how often it agrees with a
person, not before.

`JudgeScorer` nearly does this job and falls short in three ways that matter here: it cannot say a
criterion did not apply, it cannot say the judge was unreachable, and it drops the verdict's reason
codes. A judge that is down would otherwise raise, become a case error, and score the agent zero.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..core.evaluation import EvaluationCase, _await_value
from ..core.prediction import MultiScoreResult, Unmeasured
from .judging import JudgeClient
from .outcome import answer_of

logger = logging.getLogger(__name__)

PROMPT = """You are checking whether an analyst's conclusions follow from the data they showed.

Question asked:
{question}

Answer given:
{answer}

Judge only whether the interpretation is supported by the figures and findings the answer itself
states. Do not check whether those figures are correct; that is measured separately.

Reply with only JSON: {{"outcome": "supported" | "partly_supported" | "unsupported" | "no_claims",
"codes": ["..."]}} where codes name what went wrong, or [] when nothing did."""

# Outcome label -> what it is worth. "no_claims" is not a score: an answer that drew no conclusion
# has nothing to interpret, which is different from interpreting badly.
OUTCOMES: Mapping[str, float | None] = {
    "supported": 1.0,
    "partly_supported": 0.5,
    "unsupported": 0.0,
    "no_claims": None,
}


@dataclass(frozen=True, slots=True)
class Interpretation:
    """Scores whether an answer's conclusions follow from the data it showed.

    `question_of` reads the question from the case, because where a project keeps it is a project's
    business. Everything else is fixed so two runs of the same judge are comparable.
    """

    client: JudgeClient
    question_of: Callable[[EvaluationCase], str] = lambda case: str(case.inputs.get("prompt", ""))
    outcomes: Mapping[str, float | None] = field(default_factory=lambda: dict(OUTCOMES))
    name: str = "interpretation"
    experimental: bool = True

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult | Unmeasured | None:
        question = self.question_of(case)
        if not question.strip():
            return Unmeasured("the case carries no question, so there is nothing to interpret against")

        prompt = PROMPT.format(question=question, answer=answer_of(output))
        try:
            reply = await _await_value(self.client(prompt))
        except Exception as error:  # noqa: BLE001 -- an unreachable judge has no verdict to give
            logger.info("The interpretation judge raised", exc_info=True)
            return Unmeasured(f"the judge was unreachable: {type(error).__name__}: {error}")

        verdict = _parsed(str(reply))
        if verdict is None:
            # A reply nobody can read is not a verdict. Scoring it zero would call the answer wrong
            # on the strength of the judge having malfunctioned.
            return Unmeasured("the judge's reply could not be read as a verdict")

        outcome, codes = verdict
        if outcome not in self.outcomes:
            return Unmeasured(f"the judge gave outcome {outcome!r}, which has no score")
        score = self.outcomes[outcome]
        if score is None:
            return None  # nothing to interpret; the criterion does not apply to this answer
        return MultiScoreResult({self.name: score}, {self.name: {"outcome": outcome, "codes": list(codes)}})


def _parsed(reply: str) -> tuple[str, list[str]] | None:
    """The outcome and codes in a model's reply, or None when it is not readable as one.

    Scans for the first object rather than requiring the whole reply to be JSON, because a model
    asked for JSON often supplies a sentence around it.
    """

    start = reply.find("{")
    if start < 0:
        return None
    try:
        decoded, _ = json.JSONDecoder().raw_decode(reply[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    outcome = decoded.get("outcome")
    if not isinstance(outcome, str) or not outcome.strip():
        return None
    raw_codes = decoded.get("codes")
    codes = [str(code) for code in raw_codes] if isinstance(raw_codes, (list, tuple)) else []
    return outcome.strip(), codes


__all__ = ["OUTCOMES", "PROMPT", "Interpretation"]
