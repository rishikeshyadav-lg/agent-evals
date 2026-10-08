"""Accuracy as several named criteria, rather than one number.

"Was the answer right" is not one question. An answer can state every figure correctly and still be
about the wrong customer, leave out half of what was asked, draw the opposite conclusion from its own
data, or quote a number no source supports. Those are different failures with different fixes, and a
single accuracy score averages them into something nobody can act on. One real run showed why: 81% of
answers were judged correct, and 45% of those correct answers did not cover what was asked.

So accuracy is a rubric: named criteria, each scored by whatever tool actually fits, rolled up with
weights into one headline you can still quote. Figures are checked by arithmetic against your tables,
because subtraction is cheap, instant and identical every run. Completeness and interpretation need a
model to read the answer. Both are criteria of the same rubric rather than separate scores that leave
a reader guessing how they relate.

Nothing here names your criteria for you. `SUGGESTED_CRITERIA` records the five a production agent
arrived at, as a starting point and not a requirement.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.evaluation import EvaluationCase, _await_value
from ..core.prediction import MultiScoreResult, ScoreValue, Unmeasured, normalize_scores
from .outcome import WeightedRubric, score_rubric

logger = logging.getLogger(__name__)

# What one production agent settled on, with the weights it uses. Offered as a starting point: the
# criteria that matter are yours, and so are the weights.
SUGGESTED_CRITERIA: Mapping[str, float] = {
    "figures": 0.40,  # the numbers it stated are right
    "scope": 0.20,  # it is about the thing that was asked about
    "grounding": 0.15,  # every claim traces to a source; nothing invented
    "completeness": 0.15,  # it covered what was asked
    "interpretation": 0.10,  # the conclusions and direction words follow from the data
}


def _no_failure_codes(case: EvaluationCase, output: Any) -> Sequence[str]:
    return ()


def _requires_from_case(case: EvaluationCase) -> Sequence[str]:
    """Which criteria this question needs answered, from `expected["requires"]`.

    Declared by the case rather than inferred from the question's words. Deciding that "notable
    trends" demands an interpretation criterion is a reading of what the question means, and a
    library that made that call would be guessing on your behalf about the one thing it is supposed
    to be rigorous about.
    """

    expected = case.expected
    if not isinstance(expected, Mapping):
        return ()
    required = expected.get("requires")
    if isinstance(required, str) or not isinstance(required, Sequence):
        return ()
    return [str(name) for name in required]


CriterionValue = ScoreValue | None | Unmeasured


class Criterion(Protocol):
    """One criterion's scorer.

    Wider than `Metric`, which promises a mapping of scores: a criterion reports one score, or None
    when it does not apply to this question, or `Unmeasured` when it could not reach the truth it
    needed. Those three are different answers and the rubric treats them differently.
    """

    def __call__(self, case: EvaluationCase, output: Any) -> CriterionValue | Awaitable[CriterionValue]: ...


def _criterion_outcome(value: ScoreValue | None, *, criterion: str) -> tuple[float | None, Mapping[str, Any] | None]:
    """One criterion's score and its explanation.

    None means the criterion does not apply — a question with no figures in it cannot have its
    figures be wrong — and `score_rubric` drops it from the denominator rather than scoring it zero.
    The detail comes back too: a criterion that cannot say which field disagreed is of little use.
    """

    if value is None:
        return None, None
    scores, details = normalize_scores(value, scorer=criterion)
    if len(scores) != 1:
        raise ValueError(f"the scorer for criterion {criterion!r} must report one score, not {sorted(scores)}")
    name, score = next(iter(scores.items()))
    return score, details.get(name)


@dataclass(frozen=True, slots=True)
class AnswerRubric:
    """Scores one answer against several accuracy criteria and reports the roll-up with the parts.

    Each criterion has its own scorer, which may return a single score, a `ScoreResult`, or None when
    the criterion does not apply. The result carries the headline under `name` and each criterion
    under `name.criterion`, so a report can show the breakdown behind the number.
    """

    criteria: Mapping[str, Criterion]
    rubric: WeightedRubric
    failure_codes_of: Callable[[EvaluationCase, Any], Sequence[str]] = _no_failure_codes
    requires_of: Callable[[EvaluationCase], Sequence[str]] = _requires_from_case
    name: str = "accuracy"

    def __post_init__(self) -> None:
        named = set(self.criteria)
        weighted = set(self.rubric.weights)
        if named != weighted:
            raise ValueError(
                "every criterion needs a weight and every weight a criterion; "
                f"scorers without weights={sorted(named - weighted)}, "
                f"weights without scorers={sorted(weighted - named)}"
            )

    async def __call__(self, case: EvaluationCase, output: Any) -> MultiScoreResult:
        scores: dict[str, float | None] = {}
        details: dict[str, Mapping[str, Any]] = {}
        unmeasured: dict[str, str] = {}
        inapplicable: list[str] = []

        for criterion, scorer in self.criteria.items():
            try:
                value = await _await_value(scorer(case, output))
            except Exception as error:  # noqa: BLE001 -- a scorer that broke has no verdict to give
                # A judge that is down, rate-limited or returned unparseable text is a failure of the
                # measurement, not of the agent. Left to propagate it becomes a case error, and a case
                # error is scored 0.0 -- so a flaky model would quietly report the agent as wrong.
                logger.info("Criterion %r raised", criterion, exc_info=True)
                unmeasured[criterion] = f"the criterion raised: {type(error).__name__}: {error}"
                continue
            if isinstance(value, Unmeasured):
                unmeasured[criterion] = value.reason
                continue
            score, detail = _criterion_outcome(value, criterion=criterion)
            scores[criterion] = score
            if score is None:
                inapplicable.append(criterion)
            elif detail:
                details[f"{self.name}.{criterion}"] = detail

        # A question asking for three things, scored on one, must not report a headline. Figures
        # being right says nothing about trends nobody checked, and calling that accuracy is how an
        # answer covering a third of the question scored full marks.
        for required in self.requires_of(case):
            if required in unmeasured:
                continue
            if required not in self.criteria:
                unmeasured[required] = "the question requires this and no criterion scores it"
            elif scores.get(required) is None:
                unmeasured[required] = "the question requires this and its criterion did not apply"

        reported: dict[str, float] = {
            f"{self.name}.{criterion}": score for criterion, score in scores.items() if score is not None
        }
        # Always reported, so the reason a headline is missing has somewhere to live and so a report
        # can say how many cases went unchecked.
        reported[f"{self.name}.measured"] = 0.0 if (unmeasured or not reported) else 1.0
        details[f"{self.name}.measured"] = {
            "unmeasured": dict(unmeasured),
            "did_not_apply": list(inapplicable),
        }

        if unmeasured or not any(score is not None for score in scores.values()):
            # The weighted average of whatever happened to work is not accuracy, and reporting it as
            # accuracy is how an unchecked answer scores full marks. Withholding the headline is what
            # lets a suite exclude the case instead of believing a number nobody earned.
            return MultiScoreResult(reported, details)

        for criterion in self.criteria:
            scores.setdefault(criterion, None)
        result = score_rubric(self.rubric, scores, failure_codes=tuple(self.failure_codes_of(case, output)))
        reported[self.name] = result.score
        details[self.name] = {
            "passed": result.passed,
            "applicable": list(result.applicable),
            "effective_weights": dict(result.effective_weights),
            "failure_codes": list(result.failure_codes),
        }
        return MultiScoreResult(reported, details)


def suggested_rubric(*, minimum_score: float = 0.85, required_full_score: Sequence[str] = ()) -> WeightedRubric:
    """A `WeightedRubric` over `SUGGESTED_CRITERIA`, for a team that has no opinion yet."""

    return WeightedRubric(
        weights=dict(SUGGESTED_CRITERIA),
        minimum_score=minimum_score,
        required_full_score=tuple(required_full_score),
    )
