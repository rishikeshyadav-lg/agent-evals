"""Keeping drafts between `draft` and `review`, so a slow human review survives interruption."""

from __future__ import annotations

from pathlib import Path

from agent_evals.drafting import Draft, store, verify

FIELDS = {"spend": "spent"}


def _verified(case_id: str = "q1") -> Draft:
    draft = Draft(case_id=case_id, question="how did it do?", sql="SELECT ...", fields=FIELDS)
    return draft.checked(verify([{"spend": 18450.0}], FIELDS))


def test_a_draft_round_trips_with_the_row_it_returned(tmp_path: Path) -> None:
    """The row has to survive the file, or review after a restart shows SQL and nothing else."""

    store.save(tmp_path, {"q1": _verified()})

    loaded = store.load(tmp_path)

    assert loaded["q1"].check.row == {"spend": 18450.0}
    assert loaded["q1"].status == "verified"


def test_an_approval_survives_a_restart(tmp_path: Path) -> None:
    store.save(tmp_path, {"q1": _verified().approve("looked right")})

    assert store.load(tmp_path)["q1"].scoreable


def test_drafting_again_does_not_undo_a_decision(tmp_path: Path) -> None:
    """A second draft run replacing an approval with a fresh unreviewed query would undo review
    silently, which is the one thing this stage exists to prevent."""

    approved = {"q1": _verified().approve()}

    merged = store.merge(approved, [Draft(case_id="q1", question="q", sql="A DIFFERENT QUERY")])

    assert merged["q1"].status == "approved"
    assert merged["q1"].sql == "SELECT ..."


def test_new_drafts_are_added_alongside_old_decisions(tmp_path: Path) -> None:
    merged = store.merge({"q1": _verified().approve()}, [Draft(case_id="q2", question="q", sql="...")])

    assert sorted(merged) == ["q1", "q2"]


def test_no_file_means_no_drafts_rather_than_an_error(tmp_path: Path) -> None:
    assert store.load(tmp_path) == {}
