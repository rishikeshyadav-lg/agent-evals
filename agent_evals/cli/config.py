"""The `agent-evals.toml` a project keeps at its root, and how it is read and written.

TOML because the standard library reads it (`tomllib`, 3.11+) and a person has to edit it by hand.
Writing it needs a small emitter of our own: `tomllib` only reads, and pulling in a writer would add
a dependency to a tool whose point is not having many. The config is flat and we control its shape,
so the emitter stays short and does not pretend to be general.

Nothing secret goes in here. Credentials come from the environment the agent already uses, so this
file is safe to commit and to read in a review.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

FILENAME = "agent-evals.toml"


class ConfigError(RuntimeError):
    """The config is missing, malformed, or describes something that cannot work."""


@dataclass(frozen=True, slots=True)
class Config:
    """What one project needs before anything can run.

    `agent` names the deployment under test and `database` the adapter behind `open_executor`; both
    are names, never credentials. `logs` is the directory this tool writes to, relative to the root.
    """

    agent: str
    database: str = "sqlite"
    database_settings: Mapping[str, Any] = field(default_factory=dict)
    table: str = ""
    logs: str = "eval-logs"
    traces: Mapping[str, Any] = field(default_factory=dict)
    otlp_endpoint: str = ""

    def __post_init__(self) -> None:
        if not self.agent.strip():
            raise ConfigError("agent must name the deployment under test")


def path_in(root: Path) -> Path:
    return root / FILENAME


def load(root: Path) -> Config:
    """Read the config, or say plainly that `init` has not been run."""

    path = path_in(root)
    if not path.exists():
        raise ConfigError(f"no {FILENAME} in {root}. Run `agent-evals init` first.")
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error
    known = {f for f in Config.__dataclass_fields__}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"{path} has settings this version does not know: {', '.join(unknown)}")
    try:
        return Config(**raw)
    except TypeError as error:
        raise ConfigError(f"{path} is missing a required setting: {error}") from error


def save(root: Path, config: Config) -> Path:
    path = path_in(root)
    path.write_text(_to_toml(asdict(config)))
    return path


def _to_toml(values: Mapping[str, Any]) -> str:
    """Emit a flat mapping as TOML, tables last so they cannot swallow the keys after them.

    A TOML table header applies to everything below it, so a plain key written after one silently
    becomes part of that table. Sorting scalars first is the whole trick.
    """

    scalars = {k: v for k, v in values.items() if not isinstance(v, Mapping)}
    tables = {k: v for k, v in values.items() if isinstance(v, Mapping)}
    lines = [f"{key} = {_value(value)}" for key, value in scalars.items()]
    for name, table in tables.items():
        if not table:
            continue
        lines.append(f"\n[{name}]")
        lines += [f"{key} = {_value(value)}" for key, value in table.items()]
    return "\n".join(lines) + "\n"


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


__all__ = ["FILENAME", "Config", "ConfigError", "load", "path_in", "save"]
