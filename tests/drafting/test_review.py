"""The gate a generated query must pass before anything is scored against it.

A wrong reference query and a wrong agent produce the identical report line. These tests are what
stops a draft nobody checked becoming a confident number.
"""

from __future__ import annotations

import pytest

from agent_evals.drafting import Draft, reference_for, verify

FIELDS = {"spend": "spent", "clicks": "clicks"}


def _draft() -> Draft:
    return Draft(case_id="q1", question="how did 109778 do?", sql="SELECT ...", fields=FIELDS)


def test_one_row_of_finite_numbers_is_verified() -> None:
    checked = _draft().checked(verify([{"spend": 18450.0, "clicks": 400}], FIELDS))

    assert checked.status == "verified"
    assert checked.check.row == {"spend": 18450.0, "clicks": 400}


def test_two_rows_are_refused_rather_than_guessed() -> None:
    """Which row is the answer is a question only the author can settle."""

    checked = _draft().checked(verify([{"spend": 1.0, "clicks": 2}, {"spend": 3.0, "clicks": 4}], FIELDS))

    assert checked.status == "rejected"
    assert "2 rows" in checked.note


def test_no_rows_is_refused() -> None:
    assert _draft().checked(verify([], FIELDS)).status == "rejected"


def test_an_all_empty_row_blames_the_filter_not_the_data() -> None:
    """An aggregate over no matching rows returns one row of nulls. Calling that bad data sends the
    author to the columns when the fault is the WHERE clause."""

    checked = _draft().checked(verify([{"spend": None, "clicks": None}], FIELDS))

    assert "matched nothing" in checked.note


def test_one_empty_column_still_reports_that_column() -> None:
    checked = _draft().checked(verify([{"spend": 18450.0, "clicks": None}], FIELDS))

    assert "clicks is not a finite number" in checked.note


def test_a_missing_column_is_named() -> None:
    checked = _draft().checked(verify([{"spend": 18450.0}], FIELDS))

    assert "no column for clicks" in checked.note


def test_a_rejected_draft_cannot_be_approved() -> None:
    """The error path that matters most: approval must be impossible without a usable row."""

    checked = _draft().checked(verify([], FIELDS))

    with pytest.raises(ValueError, match="cannot be approved"):
        checked.approve()


def test_an_unrun_draft_cannot_be_approved() -> None:
    """A reviewer shown only SQL is reviewing syntax, and syntax is not what goes wrong here."""

    with pytest.raises(ValueError, match="has not been run"):
        _draft().approve()


def test_rejecting_needs_a_reason() -> None:
    checked = _draft().checked(verify([{"spend": 1.0, "clicks": 2}], FIELDS))

    with pytest.raises(ValueError, match="needs a reason"):
        checked.reject("  ")


def test_only_an_approved_draft_becomes_a_reference() -> None:
    """Verified is not enough. A person has to have looked at the row and said so."""

    checked = _draft().checked(verify([{"spend": 18450.0, "clicks": 400}], FIELDS))

    with pytest.raises(ValueError, match="only an approved draft"):
        reference_for(checked)

    assert reference_for(checked.approve())["parameters"] == {}
