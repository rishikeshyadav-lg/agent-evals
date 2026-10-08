"""Whether an answer is about the thing the question asked about.

One recorded baseline had nine of eleven failures turn on scope alone: the figures were right, and
they were the right figures for the wrong campaign.
"""

from __future__ import annotations

from agent_evals import EvaluationCase, PredictionResult, Unmeasured
from agent_evals.scoring.scope import EntityScope

SCOPE = EntityScope()
PATTERN = r"\b1\d{5}\b"


def _case(**overrides: object) -> EvaluationCase:
    declared = {"entity": "109249", "pattern": PATTERN}
    declared.update(overrides)
    return EvaluationCase("q", {}, expected={"scope": declared})


def _score(answer: str, case: EvaluationCase | None = None) -> object:
    return SCOPE(case or _case(), PredictionResult(answer=answer))


def test_an_answer_about_the_right_entity_scores_one() -> None:
    assert _score("Campaign 109249 spent $8,392,901.").scores["scope"] == 1.0


def test_an_answer_about_a_different_entity_scores_zero_and_names_both() -> None:
    """The failure worth catching: right figures, wrong campaign."""

    result = _score("Campaign 109778 spent $18,450.")

    assert result.scores["scope"] == 0.0
    assert result.details["scope"] == {"expected": "109249", "answered_about": ["109778"]}


def test_naming_the_right_entity_alongside_others_still_scores_one() -> None:
    """A comparison legitimately names both, so the others are recorded rather than penalised.

    Whether it actually fetched the right one cannot be told from text; that needs the agent's own
    tool arguments.
    """

    result = _score("109249 outspent 109778 by 3x.")

    assert result.scores["scope"] == 1.0
    assert result.details["scope"]["also_named"] == ["109778"]


def test_an_alias_counts_as_the_entity() -> None:
    """An agent writes the campaign's name, not the id it was asked by."""

    case = _case(aliases=["Progressive Insurance FY26"])

    assert _score("Progressive Insurance FY26 delivered 592M impressions.", case).scores["scope"] == 1.0


def test_an_answer_naming_nothing_is_unmeasured_not_wrong() -> None:
    """There is no evidence either way, and scoring zero would call the agent wrong on no evidence."""

    result = _score("The campaign performed in line with expectations.")

    assert isinstance(result, Unmeasured)
    assert "names no entity" in result.reason


def test_without_a_pattern_a_wrong_entity_cannot_be_recognised() -> None:
    """Honest limit: "109778" is only another campaign id because the case said what one looks like.
    Reporting unmeasured beats inventing a verdict the case gave no way to reach."""

    case = EvaluationCase("q", {}, expected={"scope": {"entity": "109249"}})

    assert isinstance(_score("Campaign 109778 spent $18,450.", case), Unmeasured)


def test_a_case_declaring_no_entity_is_unmeasured() -> None:
    assert isinstance(_score("anything", EvaluationCase("q", {}, expected={})), Unmeasured)


def test_a_broken_pattern_does_not_take_the_run_down() -> None:
    """A bad regex in one case must not raise through the rubric and score the agent zero."""

    case = _case(pattern="(unclosed")

    assert _score("Campaign 109249 spent $1.", case).scores["scope"] == 1.0


def test_the_entity_is_matched_on_word_boundaries() -> None:
    """"109249" must not be found inside "1092490", which is a different campaign.

    With a pattern wide enough to see it, the longer id is recognised as another entity, so this
    reads as the wrong campaign rather than as no evidence.
    """

    result = _score("Campaign 1092490 spent $1.", _case(pattern=r"\b\d{6,7}\b"))

    assert result.scores["scope"] == 0.0
    assert result.details["scope"]["answered_about"] == ["1092490"]
