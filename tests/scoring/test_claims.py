"""Reading the figures an agent stated out of the prose it wrote."""

from __future__ import annotations

import pytest

from agent_evals.scoring.claims import number_near, numbers_in_text

ANSWER = "Northwind delivered 1,240,000 impressions, a CTR of 0.42% and spend of $18,450."


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("spend was $18,450", 18_450.0),
        ("1.2M impressions", 1_200_000.0),
        ("800k clicks", 800_000.0),
        ("2.1 billion", 2_100_000_000.0),
        ("a loss of -4,200", -4_200.0),
    ],
)
def test_a_number_is_read_however_it_is_written(text: str, value: float) -> None:
    assert numbers_in_text(text)[0].value == pytest.approx(value)


def test_shorthand_is_marked_because_it_rounded_before_we_saw_it() -> None:
    """A tolerance can widen for "1.2M" only if it knows the claim was abbreviated."""

    assert numbers_in_text("1.2M impressions")[0].abbreviated is True
    assert numbers_in_text("1,200,000 impressions")[0].abbreviated is False


def test_a_percentage_keeps_its_face_value_and_says_it_was_one() -> None:
    """Whether 0.42% means 0.42 or 0.0042 depends on the table, so it is reported, not guessed."""

    stated = numbers_in_text("a CTR of 0.42%")[0]

    assert stated.value == pytest.approx(0.42)
    assert stated.percent is True


def test_a_decimal_before_a_letter_is_not_truncated() -> None:
    """The campaign hit this: a trailing word boundary made "1.31x" read as 1."""

    assert numbers_in_text("frequency 1.31x")[0].value == pytest.approx(1.31)


def test_a_unit_suffix_is_not_mistaken_for_a_magnitude() -> None:
    assert numbers_in_text("a 5kb payload")[0].value == pytest.approx(5.0)


@pytest.mark.parametrize("label", ["impressions", "CTR", "ctr", "spend"])
def test_the_figure_beside_a_label_is_found_whichever_side_it_sits(label: str) -> None:
    assert number_near(ANSWER, label) is not None


def test_a_label_before_or_after_its_number_both_work() -> None:
    assert number_near("spend was $18,450", "spend").value == pytest.approx(18_450.0)
    assert number_near("$18,450 of spend", "spend").value == pytest.approx(18_450.0)


def test_the_nearest_number_wins_when_several_are_close() -> None:
    assert number_near(ANSWER, "CTR").value == pytest.approx(0.42)


def test_a_label_that_is_absent_gives_nothing_rather_than_a_guess() -> None:
    """"We found no figure for clicks" is a different report from "the agent was wrong"."""

    assert number_near(ANSWER, "clicks") is None


def test_a_label_with_no_number_near_it_gives_nothing() -> None:
    assert number_near("clicks were not reported in this period at all", "clicks", window=5) is None


def test_an_empty_label_is_refused() -> None:
    """The error path: an empty label would match everywhere and return the first number on the page."""

    with pytest.raises(ValueError, match="non-empty"):
        number_near(ANSWER, "   ")
