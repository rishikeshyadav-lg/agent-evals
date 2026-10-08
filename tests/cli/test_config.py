"""Reading and writing the project's agent-evals.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from agent_evals.cli.config import Config, ConfigError, load, save


def test_a_config_round_trips(tmp_path: Path) -> None:
    written = Config(agent="rc1", database="databricks", table="catalog.schema.table")

    save(tmp_path, written)

    assert load(tmp_path) == written


def test_tables_are_written_last_so_they_do_not_swallow_later_keys(tmp_path: Path) -> None:
    """A TOML table header claims everything below it, so a scalar written after one joins it."""

    save(tmp_path, Config(agent="rc1", database_settings={"warehouse_id": "abc"}, logs="eval-logs"))

    parsed = tomllib.loads((tmp_path / "agent-evals.toml").read_text())

    assert parsed["logs"] == "eval-logs"
    assert parsed["database_settings"] == {"warehouse_id": "abc"}


def test_a_missing_config_says_to_run_init(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="init"):
        load(tmp_path)


def test_a_setting_this_version_does_not_know_is_refused(tmp_path: Path) -> None:
    """Silently ignoring it would let a typo turn a configured run into a differently configured one."""

    (tmp_path / "agent-evals.toml").write_text('agent = "rc1"\ntabel = "typo"\n')

    with pytest.raises(ConfigError, match="tabel"):
        load(tmp_path)


def test_an_agent_must_be_named() -> None:
    with pytest.raises(ConfigError, match="agent"):
        Config(agent="  ")


def test_broken_toml_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "agent-evals.toml").write_text("agent = \n")

    with pytest.raises(ConfigError, match="not valid TOML"):
        load(tmp_path)
