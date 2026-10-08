"""Turning mined questions into a dataset that can be mined again and compared.

The property these protect: mine the same window twice and get the same checksum. Without it, every
comparison across time silently measures two different datasets.
"""

from __future__ import annotations

import pytest

from agent_evals.mining import MinedQuestion, build_dataset, build_manifest, deduplicate, question_id

ASKED = [
    MinedQuestion("How did campaign 109778 do?", "tr-c", recorded_at="2026-09-03T10:00:00+00:00"),
    MinedQuestion("What is the CTR for 100412?", "tr-a", recorded_at="2026-09-01T09:00:00+00:00"),
    MinedQuestion("how did  CAMPAIGN 109778 do?", "tr-b", recorded_at="2026-09-02T11:00:00+00:00"),
]


def test_the_same_question_asked_twice_becomes_one_case() -> None:
    """Case and spacing differ but the question does not, so the dataset must not hold it twice."""

    assert len(deduplicate(ASKED)) == 2


def test_a_duplicate_keeps_its_earliest_occurrence() -> None:
    """The earliest is the one still in the window next time. Keeping the newest would change the
    dataset on every run, which is the thing the checksum exists to detect."""

    kept = {question_id(m.question): m for m in deduplicate(ASKED)}

    assert kept[question_id("How did campaign 109778 do?")].trace_id == "tr-b"


def test_the_checksum_does_not_depend_on_the_order_traces_came_back() -> None:
    """A backend promises no order, so the digest must not either."""

    first = build_manifest(build_dataset(ASKED, dataset_id="real", version="v1"))
    shuffled = build_manifest(build_dataset(list(reversed(ASKED)), dataset_id="real", version="v1"))

    assert first.digest == shuffled.digest


def test_a_case_id_comes_from_the_question_not_the_trace() -> None:
    """Two people asking the same thing must land on one case, and a trace falling out of the
    window must not renumber everything."""

    assert question_id("How did X do?") == question_id("  how did   x do?  ")


def test_mining_nothing_says_so_rather_than_writing_an_empty_dataset() -> None:
    with pytest.raises(ValueError, match="no questions"):
        build_dataset([], dataset_id="real", version="v1")


def test_a_classifier_of_yours_decides_the_category() -> None:
    """What the categories are is domain knowledge; a library guessing would be wrong invisibly."""

    dataset = build_dataset(
        ASKED[:1], dataset_id="real", version="v1", classify=lambda mined: "overall_summary"
    )

    assert dataset.cases[0].inputs["category"] == "overall_summary"


def test_a_blank_question_is_refused_at_the_source() -> None:
    with pytest.raises(ValueError, match="blank"):
        MinedQuestion("   ", "tr-a")


def test_a_question_must_say_which_trace_it_came_from() -> None:
    """The trace id is the only way back to the conversation, so it cannot be optional."""

    with pytest.raises(ValueError, match="which trace"):
        MinedQuestion("a real question", "")
