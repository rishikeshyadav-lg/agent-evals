"""Proposing a query for a question, and declining when there is nothing honest to propose."""

from __future__ import annotations

import pytest

from agent_evals.drafting import FirstMatch, TemplateDrafter
from agent_evals.mining import MinedQuestion

TEMPLATE = TemplateDrafter(
    sql="SELECT SUM(spend) AS spend FROM delivery WHERE acid = :acid",
    pattern=r"\b(1\d{5})\b",
    parameter="acid",
    fields={"spend": "spent"},
)


def test_a_matching_question_gets_its_value_bound() -> None:
    drafted = TEMPLATE(MinedQuestion("How is campaign 109778 performing?", "tr-a"))

    assert drafted is not None
    assert drafted.parameters == {"acid": "109778"}


def test_a_question_the_pattern_does_not_match_gets_no_draft() -> None:
    """Declining is a first-class answer. A drafter that always produces something produces
    nonsense for what it does not understand, and nonsense that runs is the whole danger."""

    assert TEMPLATE(MinedQuestion("What should I do about pacing?", "tr-b")) is None


def test_a_pattern_must_capture_exactly_one_value() -> None:
    """Two groups means the author expected something this cannot deliver; saying so beats
    silently binding the first."""

    with pytest.raises(ValueError, match="exactly one"):
        TemplateDrafter(sql="...", pattern=r"(\d+)-(\d+)", parameter="acid", fields={"spend": "spend"})


def test_a_draft_with_no_fields_is_refused() -> None:
    with pytest.raises(ValueError, match="never score"):
        TemplateDrafter(sql="...", pattern=r"(\d+)", parameter="acid", fields={})


@pytest.mark.asyncio
async def test_the_first_drafter_that_offers_something_wins() -> None:
    """Order is the policy: trusted templates ahead of anything that guesses."""

    never = TemplateDrafter(sql="never", pattern=r"\b(zzz\d+)\b", parameter="x", fields={"spend": "spend"})
    chain = FirstMatch(drafters=[never, TEMPLATE])

    drafted = await chain(MinedQuestion("How is campaign 109778 performing?", "tr-a"))

    assert drafted is not None
    assert drafted.sql.startswith("SELECT SUM(spend)")


@pytest.mark.asyncio
async def test_a_chain_where_nobody_offers_anything_returns_nothing() -> None:
    chain = FirstMatch(drafters=[TEMPLATE])

    assert await chain(MinedQuestion("What should I do about pacing?", "tr-b")) is None
