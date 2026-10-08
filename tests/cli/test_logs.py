"""Keeping customer text out of a commit, when the log directory lives inside the repository.

The convenient place for logs and the safe place are not the same, and the convenient one was chosen.
These tests are the thing standing between that choice and a commit full of customer questions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_evals.cli.logs import LogsNotIgnored, inspect_location, prepare


def _repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_preparing_a_directory_makes_git_ignore_it(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    location = prepare(root)

    assert location.safe
    assert "eval-logs/" in (root / ".gitignore").read_text()


def test_both_layers_are_written_not_just_the_one_that_happens_to_suffice(tmp_path: Path) -> None:
    """The inner file alone satisfies the check, which once hid the fact that the root entry was
    never written. Two layers were promised; a lost root entry must still leave the directory safe."""

    root = _repository(tmp_path)
    prepare(root)

    (root / ".gitignore").write_text("")

    assert inspect_location(root / "eval-logs").safe


def test_a_written_log_is_not_staged(tmp_path: Path) -> None:
    """The whole point, end to end: a log holding customer text never reaches `git status`."""

    root = _repository(tmp_path)
    prepare(root)
    (root / "eval-logs" / "run.jsonl").write_text('{"question": "customer text"}\n')

    staged = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout

    assert "eval-logs" not in staged


def test_an_unignored_directory_refuses_to_be_used(tmp_path: Path) -> None:
    """The error path. Silently writing here would put customer questions in the next commit."""

    root = _repository(tmp_path)
    prepare(root)
    (root / ".gitignore").write_text("")
    (root / "eval-logs" / ".gitignore").unlink()

    with pytest.raises(LogsNotIgnored, match="would be committed"):
        inspect_location(root / "eval-logs").require_safe()


def test_the_refusal_names_the_line_to_add(tmp_path: Path) -> None:
    """A guard that blocks without saying how to proceed gets worked around rather than fixed."""

    root = _repository(tmp_path)
    (root / "eval-logs").mkdir()

    with pytest.raises(LogsNotIgnored, match=r"eval-logs/"):
        inspect_location(root / "eval-logs").require_safe()


def test_outside_a_repository_there_is_nothing_to_guard_against(tmp_path: Path) -> None:
    location = inspect_location(tmp_path / "eval-logs")

    assert location.safe
    assert not location.inside_repository


def test_an_existing_gitignore_keeps_its_contents(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / ".gitignore").write_text(".venv\n")

    prepare(root)

    assert (root / ".gitignore").read_text() == ".venv\neval-logs/\n"
