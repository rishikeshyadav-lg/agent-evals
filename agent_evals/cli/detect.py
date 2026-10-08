"""Finding the settings a project already wrote down, so nobody has to type them twice.

Every value the first version of `init` asked for -- the table, the warehouse, the catalog, the
MLflow experiment, which deployment -- was already sitting in the project's own deploy files, and
the credentials were already in the Databricks config. Asking for them was asking someone to copy
text from one file on their disk into another.

So this reads what is there and proposes it. Nothing is applied silently: `init` shows what it found
and the person picks. The heuristics are deliberately shallow -- key names and file shapes, no
parsing of any particular product's schema -- because a detector that is clever about one project is
wrong about the next, and a wrong guess presented confidently is worse than a prompt.
"""

from __future__ import annotations

import configparser
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Files worth reading: deployment manifests and environment files, nothing deeper.
CANDIDATE_GLOBS = ("**/*.app.yaml", "**/*.app.yml", "**/app.yaml", "**/*.env", ".env", "**/env.yaml")
SKIP_DIRECTORIES = {".git", ".venv", "node_modules", "__pycache__", "eval-logs", ".mypy_cache"}
MAX_FILES = 40

# A found key counts towards a setting when its name contains one of these words. Shallow on
# purpose: these are proposals a person confirms, not conclusions.
WANTED: Mapping[str, tuple[str, ...]] = {
    "table": ("TABLE_FULL_NAME", "TABLE_NAME", "FULL_TABLE"),
    "warehouse_id": ("WAREHOUSE_ID", "WAREHOUSE"),
    "catalog": ("CATALOG",),
    "schema": ("SCHEMA",),
    "experiment_id": ("EXPERIMENT_ID",),
    "host": ("DATABRICKS_HOST", "WORKSPACE_URL"),
}


@dataclass(frozen=True, slots=True)
class Found:
    """One value a file offered, and where it came from so a person can check it."""

    value: str
    source: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Deployment:
    """One deployment the project defines, with the settings its own file records.

    Grouped per deployment rather than pooled, because a repository holds several environments and
    pooling them hands you dev's experiment beside prd's table. One choice should settle all of it.
    """

    name: str
    source: str
    settings: Mapping[str, str] = field(default_factory=dict)

    def get(self, key: str, fallback: str = "") -> str:
        return self.settings.get(key, fallback)


@dataclass(frozen=True, slots=True)
class Detected:
    """Everything worth proposing: the deployments found, and the credentials already on this machine."""

    deployments: tuple[Deployment, ...] = ()
    profiles: tuple[str, ...] = ()
    shared: Mapping[str, str] = field(default_factory=dict)


def detect(root: Path) -> Detected:
    """Read the project for what it already records, and the machine for credentials."""

    per_file = {path: _settings_in(path) for path in _files(root)}
    deployments = _deployments(root, per_file)
    # Anything found in a file that names no deployment is still worth offering as a fallback.
    shared: dict[str, str] = {}
    for settings in per_file.values():
        for key, value in settings.items():
            shared.setdefault(key, value)
    return Detected(deployments=deployments, profiles=_profiles(), shared=shared)


def _settings_in(path: Path) -> dict[str, str]:
    """The wanted settings one file records, by our shallow key-name match."""

    text = _read(path)
    pairs = list(_env_style(text)) + list(_yaml_name_value(text))
    settings: dict[str, str] = {}
    for name, needles in WANTED.items():
        for key, value in pairs:
            if any(needle in key.upper() for needle in needles):
                settings.setdefault(name, value)
                break
    return settings


def _files(root: Path) -> list[Path]:
    seen: list[Path] = []
    for pattern in CANDIDATE_GLOBS:
        for path in sorted(root.glob(pattern)):
            if any(part in SKIP_DIRECTORIES for part in path.parts) or not path.is_file():
                continue
            if path not in seen:
                seen.append(path)
            if len(seen) >= MAX_FILES:
                return seen
    return seen


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=\s*(.+?)\s*$", re.MULTILINE)
# Databricks app manifests list environment as `- name: KEY` then `value: "..."` on the next lines.
_YAML_PAIR = re.compile(r"name:\s*[\"']?([A-Z][A-Z0-9_]{2,})[\"']?\s*\n\s*value:\s*[\"']?(.*?)[\"']?\s*$", re.MULTILINE)


def _env_style(text: str) -> Iterable[tuple[str, str]]:
    for key, raw in _ENV_LINE.findall(text):
        value = raw.strip().strip("\"'")
        if value and not value.startswith("${"):
            yield key, value


def _yaml_name_value(text: str) -> Iterable[tuple[str, str]]:
    for key, raw in _YAML_PAIR.findall(text):
        value = raw.strip().strip("\"'")
        if value and not value.startswith("${"):
            yield key, value


def _unique(values: Iterable[Found]) -> list[Found]:
    seen: dict[str, Found] = {}
    for found in values:
        seen.setdefault(found.value, found)
    return list(seen.values())


_DEPLOYMENT = re.compile(r"\b((?:dev|rc\d|prd|prod|stg|staging)-[a-z0-9][a-z0-9-]{3,})\b")


def _environment(name: str) -> str:
    """The leading dev/rc1/prd token, which is the part that is consistent across a project."""

    return name.split("-", 1)[0]


def _deployments(root: Path, per_file: Mapping[Path, Mapping[str, str]]) -> tuple[Deployment, ...]:
    """Deployments the project defines, each carrying the settings from its own file.

    A file is taken to define the deployment whose name appears in its own path. That is what
    separates the thing being deployed from the half-dozen other services its config merely points
    at: `deploy/rc1/rc1-campaign-performance.app.yaml` defines rc1 and mentions the rest.
    """

    found: list[Deployment] = []
    for path, settings in per_file.items():
        where = "/".join(path.parts[-2:])
        # Join on the environment token, not the whole name: the same project names its apps
        # inconsistently across environments (rc1-campaign-performance beside
        # prd-ai-campaign-performance), and a stricter match silently drops one of them.
        environments = {_environment(m) for m in _DEPLOYMENT.findall(str(path))}
        candidates = [m.split("-18")[0] for m in _DEPLOYMENT.findall(_read(path))]
        named = sorted((n for n in candidates if _environment(n) in environments), key=len)
        if named:
            found.append(Deployment(name=named[-1], source=where, settings=dict(settings)))
    by_name: dict[str, Deployment] = {}
    for deployment in found:
        kept = by_name.get(deployment.name)
        if kept is None or len(deployment.settings) > len(kept.settings):
            by_name[deployment.name] = deployment
    return tuple(by_name[name] for name in sorted(by_name))


def _profiles() -> tuple[str, ...]:
    """Databricks profiles already configured on this machine, so nobody pastes a token."""

    path = Path(os.environ.get("DATABRICKS_CONFIG_FILE", Path.home() / ".databrickscfg"))
    if not path.exists():
        return ()
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return ()
    return tuple(name for name in parser.sections() if not name.startswith("__"))


def host_for_profile(profile: str) -> str:
    """The workspace URL a profile points at, so the tool can set it rather than ask."""

    path = Path(os.environ.get("DATABRICKS_CONFIG_FILE", Path.home() / ".databrickscfg"))
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
        return str(parser[profile].get("host", "")).strip()
    except (configparser.Error, KeyError):
        return ""


__all__ = ["Detected", "Found", "detect", "host_for_profile"]
