"""The two commands, driven as a user drives them."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agent_evals.cli.main import app

runner = CliRunner()


def _repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_init_writes_a_config_and_an_ignored_log_directory(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    result = runner.invoke(app, ["init", "--root", str(root), "--agent", "rc1"])

    assert result.exit_code == 0
    assert (root / "agent-evals.toml").exists()
    assert "eval-logs/" in (root / ".gitignore").read_text()


def test_init_refuses_to_overwrite_an_existing_config(tmp_path: Path) -> None:
    """The config is hand-edited, so a second init must not quietly discard those edits."""

    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--agent", "rc1"])

    result = runner.invoke(app, ["init", "--root", str(root), "--agent", "other"])

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_doctor_without_a_config_says_to_run_init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "init" in result.output


def test_doctor_reports_a_log_directory_that_would_be_committed(tmp_path: Path) -> None:
    """The failure that matters: logs hold customer questions, and this run would commit them."""

    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--agent", "rc1"])
    (root / ".gitignore").write_text("")
    (root / "eval-logs" / ".gitignore").unlink()

    result = runner.invoke(app, ["doctor", "--root", str(root)])

    assert result.exit_code == 1
    assert "WOULD BE COMMITTED" in result.output


def test_doctor_names_a_missing_credential_rather_than_asking_for_one(tmp_path: Path, monkeypatch) -> None:
    """Credentials are borrowed from the agent's own environment, never prompted for or stored."""

    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--agent", "rc1", "--database", "databricks"])

    result = runner.invoke(app, ["doctor", "--root", str(root)])

    assert "DATABRICKS_HOST" in result.output
    assert result.exit_code == 1


def test_a_limited_setup_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    """No table means figures are not checked, which is a real configuration. A checker that fails
    on things that merely limit the run teaches people to ignore it."""

    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--agent", "rc1"])

    result = runner.invoke(app, ["doctor", "--root", str(root)])

    assert result.exit_code == 0
    assert "ready (with warnings)" in result.output
