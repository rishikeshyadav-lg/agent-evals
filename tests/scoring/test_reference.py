"""Checking an agent's figures against the table that holds the truth.

All offline against SQLite, so nothing here needs a warehouse or a credential. That proves the
plumbing; only your own database can tell you your own SQL asks the right question.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_evals import EvaluationCase, PredictionResult, Tolerance, Unmeasured
from agent_evals.scoring.reference import SqlReference
from agent_evals.sql import open_executor

TRUTH = {"spend": 18_450.0, "clicks": 400, "ctr": 0.0042}


def _table():
    run = open_executor("sqlite", {"path": ":memory:"})

    async def build() -> None:
        await run("CREATE TABLE delivery (campaign TEXT, spend REAL, clicks INTEGER, ctr REAL)", {})
        await run(
            "INSERT INTO delivery VALUES (:c, :s, :k, :r)",
            {"c": "spring", "s": TRUTH["spend"], "k": TRUTH["clicks"], "r": TRUTH["ctr"]},
        )

    asyncio.run(build())
    return run


def _case(**overrides) -> EvaluationCase:
    reference = {
        "sql": "SELECT spend, clicks, ctr FROM delivery WHERE campaign = :name",
        "parameters": {"name": "spring"},
        "fields": ["spend", "clicks", "ctr"],
    }
    reference.update(overrides)
    return EvaluationCase("c1", {"q": "how did spring do?"}, expected={"reference": reference})


def _score(answer: str, *, case: EvaluationCase | None = None, **kwargs):
    scorer = SqlReference(execute=_table(), fraction_fields=["ctr"], **kwargs)
    return asyncio.run(scorer(case or _case(), PredictionResult(answer=answer)))


RIGHT = "Spring had spend of $18,450, clicks 400 and ctr of 0.42%."


def test_an_answer_that_matches_the_table_scores_one() -> None:
    assert _score(RIGHT).scores["figures"] == pytest.approx(1.0)


def test_a_wrong_figure_is_named_with_the_size_of_the_disagreement() -> None:
    """A score alone tells you nothing to fix; "said 380, table says 400" tells you a lot."""

    result = _score("Spring had spend of $18,450, clicks 380 and ctr of 0.42%.")

    assert result.scores["figures"] == pytest.approx(2 / 3)
    disagreed = result.details["figures"]["disagreed"]["clicks"]
    assert disagreed["expected"] == 400
    assert disagreed["claimed"] == pytest.approx(380.0)
    assert disagreed["difference"] == pytest.approx(-20.0)


def test_a_figure_never_stated_costs_coverage_and_not_correctness() -> None:
    """A figure left out is a gap in what was covered, not a wrong number."""

    result = _score("Spring had spend of $18,450 and ctr of 0.42%.")

    assert result.scores["figures"] == pytest.approx(1.0)
    assert result.scores["figures.coverage"] == pytest.approx(2 / 3)
    assert result.details["figures.coverage"]["never_stated"] == ["clicks"]


def test_a_percentage_is_read_as_a_fraction_when_the_table_stores_one() -> None:
    assert _score(RIGHT).details["figures.measured"]["fields"]["ctr"]["matched"] is True


def test_a_percentage_is_compared_as_written_when_the_field_is_not_a_fraction() -> None:
    """Guessing that any % means a fraction would silently pass answers that are 100x out."""

    scorer = SqlReference(execute=_table())  # ctr not declared a fraction
    result = asyncio.run(scorer(_case(), PredictionResult(answer=RIGHT)))

    assert result.details["figures.measured"]["fields"]["ctr"]["matched"] is False


def test_shorthand_widens_a_relative_tolerance() -> None:
    """"1.2M" has rounded before we saw it, so holding it to exact precision fails the wording."""

    tight = Tolerance("relative", 0.001, abbreviated_multiplier=100.0)
    result = _score("spend of 18.4k, clicks 400, ctr 0.42%", tolerances={"spend": tight})

    assert result.details["figures.measured"]["fields"]["spend"]["matched"] is True


def test_figures_the_agent_returned_as_data_are_preferred_to_its_prose() -> None:
    """Reading a number out of prose is guesswork; an agent that hands back data should be trusted."""

    scorer = SqlReference(execute=_table(), fraction_fields=["ctr"])
    output = PredictionResult(answer="spend was about nine hundred", extra={"figures": dict(TRUTH)})

    result = asyncio.run(scorer(_case(), output))

    assert result.scores["figures"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"parameters": {"name": "autumn"}}, "no rows"),
        ({"sql": "SELECT spend FROM delivery"}, "no column for clicks, ctr"),
        ({"sql": "SELECT * FROM missing_table"}, "query failed"),
        ({"fields": []}, "names no fields"),
    ],
)
def test_ground_truth_that_cannot_be_had_is_named_not_scored(overrides: dict, reason: str) -> None:
    """A zero would say the agent was wrong. Nobody checked, which is a different report."""

    result = _score(RIGHT, case=_case(**overrides))

    assert "figures" not in result.scores
    assert result.scores["figures.measured"] == 0.0
    assert reason in result.details["figures.measured"]["unmeasured"]


def test_more_than_one_row_is_refused_rather_than_guessed() -> None:
    """Which row was meant is a question only the case author can answer."""

    run = _table()
    asyncio.run(run("INSERT INTO delivery VALUES ('spring', 1.0, 2, 0.003)", {}))
    scorer = SqlReference(execute=run)

    result = asyncio.run(scorer(_case(), PredictionResult(answer=RIGHT)))

    assert "returned 2 rows" in result.details["figures.measured"]["unmeasured"]


def test_a_case_with_no_reference_query_is_not_measured() -> None:
    plain = EvaluationCase("c2", {"q": "hello"}, expected="hi")

    result = _score(RIGHT, case=plain)

    assert "declares no reference query" in result.details["figures.measured"]["unmeasured"]


def test_ground_truth_returns_the_reason_object_for_a_rubric_to_use() -> None:
    """AnswerRubric needs an Unmeasured, not a score, to withhold the headline."""

    scorer = SqlReference(execute=_table())
    truth = asyncio.run(scorer.ground_truth(_case(parameters={"name": "autumn"})))

    assert isinstance(truth, Unmeasured)
    assert "no rows" in truth.reason


def _rubric(run):
    from agent_evals import WeightedRubric
    from agent_evals.scoring.answer import AnswerRubric
    from agent_evals.scoring.reference import reference_criteria

    return AnswerRubric(
        criteria=reference_criteria(SqlReference(execute=run, fraction_fields=["ctr"])),
        rubric=WeightedRubric(weights={"figures": 0.7, "completeness": 0.3}),
    )


def test_one_query_feeds_both_criteria_of_the_rubric() -> None:
    """A wrong figure and an absent one are different failures and must score differently."""

    rubric = _rubric(_table())
    case = _case()

    wrong = asyncio.run(rubric(case, PredictionResult(answer="spend $18,450, clicks 380, ctr 0.42%")))
    absent = asyncio.run(rubric(case, PredictionResult(answer="spend $18,450, ctr 0.42%")))

    assert wrong.scores["accuracy.figures"] < 1.0
    assert wrong.scores["accuracy.completeness"] == pytest.approx(1.0)
    assert absent.scores["accuracy.figures"] == pytest.approx(1.0)
    assert absent.scores["accuracy.completeness"] < 1.0


def test_each_answer_is_scored_on_its_own_figures() -> None:
    """The shared query is cached per answer. Keying that cache on id() alone handed every later
    answer the first one's scores, because CPython reuses the address of a freed object."""

    rubric = _rubric(_table())
    case = _case()
    scored = [
        asyncio.run(rubric(case, PredictionResult(answer=answer)))
        for answer in ("spend $18,450, clicks 400, ctr 0.42%", "spend $1, clicks 2, ctr 99%")
    ]

    assert scored[0].scores["accuracy.figures"] == pytest.approx(1.0)
    assert scored[1].scores["accuracy.figures"] == pytest.approx(0.0)


def test_a_rubric_withholds_accuracy_when_the_table_cannot_answer() -> None:
    """The whole chain: no ground truth, so no accuracy, and the reason travels with it."""

    result = asyncio.run(_rubric(_table())(_case(parameters={"name": "autumn"}), PredictionResult(answer=RIGHT)))

    assert "accuracy" not in result.scores
    assert "no rows" in result.details["accuracy.measured"]["unmeasured"]["figures"]


def test_an_omitted_required_asks_for_every_field() -> None:
    """The default: a case that names fields and says nothing more wants all of them stated."""

    result = _score("Spring had spend of $18,450.")

    assert result.scores["figures.coverage"] == pytest.approx(1 / 3)
    assert result.details["figures.coverage"]["never_stated"] == ["clicks", "ctr"]


def test_an_explicitly_empty_required_asks_for_none() -> None:
    """An open-ended question ("how is it performing") required nothing, so nothing can be missing.

    `or` used to collapse this into the default, charging the answer for figures nobody asked for.
    """

    result = _score("Spring had spend of $18,450.", case=_case(required=[]))

    assert "figures.coverage" not in result.scores
    assert result.scores["figures"] == pytest.approx(1.0)
