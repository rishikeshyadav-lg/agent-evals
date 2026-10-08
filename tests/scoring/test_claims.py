"""Reading the figures an agent stated out of the prose it wrote."""

from __future__ import annotations

import pytest

from agent_evals.scoring.claims import numbers_by_label, numbers_in_text

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


FIELDS = ["impressions", "CTR", "spend"]


def _value(text: str, label: str, labels: list[str] | None = None, **kwargs) -> float | None:
    stated = numbers_by_label(text, labels or FIELDS, **kwargs).get(label)
    return None if stated is None else stated.value


@pytest.mark.parametrize("label", FIELDS)
def test_every_label_gets_its_own_figure(label: str) -> None:
    assert _value(ANSWER, label) is not None


def test_a_label_before_or_after_its_number_both_work() -> None:
    """English writes it either way, so both must resolve to the same figure."""

    assert _value("spend was $18,450", "spend", ["spend"]) == pytest.approx(18_450.0)
    assert _value("$18,450 of spend", "spend", ["spend"]) == pytest.approx(18_450.0)


def test_a_field_does_not_take_the_figure_beside_another_field() -> None:
    """The bug this function exists for: "400 clicks, a ctr of 0.42%" gave clicks 0.42 when each
    label was resolved on its own, because the rule had to prefer one side or the other."""

    found = numbers_by_label("400 clicks, a ctr of 0.42%", ["clicks", "ctr"])

    assert found["clicks"].value == pytest.approx(400.0)
    assert found["ctr"].value == pytest.approx(0.42)


def test_the_nearest_number_wins_when_several_are_close() -> None:
    assert _value(ANSWER, "CTR") == pytest.approx(0.42)


def test_a_label_that_is_absent_gives_nothing_rather_than_a_guess() -> None:
    """"We found no figure for clicks" is a different report from "the agent was wrong"."""

    assert "clicks" not in numbers_by_label(ANSWER, [*FIELDS, "clicks"])


def test_a_label_with_no_number_near_it_gives_nothing() -> None:
    assert numbers_by_label("clicks were not reported at all this period", ["clicks"], window=5) == {}


def test_a_blank_label_is_refused() -> None:
    """The error path. A blank label finds no figure, so the field would be reported as never
    stated -- blaming the agent for what is really a mistake in the case."""

    with pytest.raises(ValueError, match="non-empty"):
        numbers_by_label(ANSWER, ["spend", "   "])


def test_a_label_inside_a_longer_word_is_not_matched() -> None:
    """Asking for "spend" must not read "spending"'s figure; a confident wrong number is the worst
    outcome for a tool whose job is checking figures."""

    assert _value("spending was 900, spend was 400", "spend", ["spend"]) == pytest.approx(400.0)


def test_a_number_far_from_its_label_is_read_whole() -> None:
    """A windowed slice through "18,450" once left a fragment the parser read as a sound figure:
    1845. Measuring distance over the whole text cannot cut a number at all."""

    far = "spend" + " " * 55 + "18,450"

    assert _value(far, "spend", ["spend"], window=60) == pytest.approx(18_450.0)
