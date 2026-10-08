"""The two commands, driven as a user drives them."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agent_evals.cli.config import Config, load, save
from agent_evals.cli.main import app

runner = CliRunner()


def _repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_init_writes_a_config_and_an_ignored_log_directory(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    result = runner.invoke(app, ["init", "--root", str(root), "--yes", "--agent", "rc1"])

    assert result.exit_code == 0
    assert (root / "agent-evals.toml").exists()
    assert "eval-logs/" in (root / ".gitignore").read_text()


def test_init_refuses_to_overwrite_an_existing_config(tmp_path: Path) -> None:
    """The config is hand-edited, so a second init must not quietly discard those edits."""

    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--yes", "--agent", "rc1"])

    result = runner.invoke(app, ["init", "--root", str(root), "--yes", "--agent", "other"])

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_doctor_without_a_config_says_to_run_init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "init" in result.output


def test_doctor_reports_a_log_directory_that_would_be_committed(tmp_path: Path) -> None:
    """The failure that matters: logs hold customer questions, and this run would commit them."""

    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--yes", "--agent", "rc1"])
    (root / ".gitignore").write_text("")
    (root / "eval-logs" / ".gitignore").unlink()

    result = runner.invoke(app, ["doctor", "--root", str(root)])

    assert result.exit_code == 1
    assert "WOULD BE COMMITTED" in result.output


def test_doctor_names_a_missing_credential_rather_than_asking_for_one(tmp_path: Path, monkeypatch) -> None:
    """Credentials are borrowed from the project's own profile or environment, never prompted for."""

    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    root = _repository(tmp_path)
    save(root, Config(agent="rc1", database="databricks"))

    result = runner.invoke(app, ["doctor", "--root", str(root)])

    assert "DATABRICKS_HOST" in result.output
    assert result.exit_code == 1


def test_init_detects_settings_a_project_already_records(tmp_path: Path) -> None:
    """The point of the rewrite: everything in a deploy manifest is read, not asked for."""

    root = _repository(tmp_path)
    manifest = root / "deploy" / "rc1" / "rc1-thing.app.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "env:\n"
        "  - name: DATABRICKS_APP_NAME\n    value: \"rc1-thing\"\n"
        "  - name: DELIVERY_TABLE_FULL_NAME\n    value: \"cat.sch.tbl\"\n"
        "  - name: DELIVERY_WAREHOUSE_ID\n    value: \"wh123\"\n"
        "  - name: MLFLOW_EXPERIMENT_ID\n    value: \"999\"\n"
    )

    result = runner.invoke(app, ["init", "--root", str(root), "--yes"])

    assert result.exit_code == 0
    written = load(root)
    assert written.agent == "rc1-thing"
    assert written.table == "cat.sch.tbl"
    assert written.database_settings["warehouse_id"] == "wh123"
    assert written.traces["experiment_id"] == "999"


def test_init_writes_a_drafter_that_runs(tmp_path: Path) -> None:
    """A blank file and a link to the docs is not onboarding. The scaffold has to work as written."""

    root = _repository(tmp_path)
    runner.invoke(app, ["init", "--root", str(root), "--yes", "--agent", "rc1"])

    assert not (root / "eval_drafter.py").exists()  # nothing to query, so nothing scaffolded

    save(root, Config(agent="rc1", table="cat.sch.tbl"))
    from agent_evals.cli.scaffold import write_drafter

    path = write_drafter(root, "cat.sch.tbl")

    assert path is not None
    assert "cat.sch.tbl" in path.read_text()


def test_init_never_waits_for_an_answer_that_cannot_come(tmp_path: Path) -> None:
    """A script must fail with the flag to pass, not hang on a prompt nobody will see."""

    result = runner.invoke(app, ["init", "--root", str(_repository(tmp_path)), "--yes"])

    assert result.exit_code == 1
    assert "--agent" in result.output
