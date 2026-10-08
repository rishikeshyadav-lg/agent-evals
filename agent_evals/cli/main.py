"""The `agent-evals` command: set a project up, then check it can actually run.

Two commands so far. `init` writes the config and makes the log directory safe to write into;
`doctor` answers "will a run work from here", which is the question worth asking before spending
money on one.

Credentials are never asked for and never stored. The agent already authenticates to its warehouse,
so this reads the same environment and says which variable is missing when it cannot.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

try:
    import typer
except ImportError as error:  # pragma: no cover - exercised by the install, not the suite
    raise SystemExit('the CLI needs its extra. Install it with: pip install "agent-evals[cli]"') from error

from . import config as configuration
from . import logs as logging_directory

app = typer.Typer(add_completion=False, help="Evaluate an agent against real questions and your own tables.")

# Read, never written or asked for. The agent already has these; the tool borrows them.
CREDENTIAL_VARIABLES = {
    "databricks": ("DATABRICKS_HOST",),
    "sqlite": (),
}


@app.command()
def init(
    root: Path = typer.Option(Path("."), help="the agent's root directory"),
    agent: str = typer.Option(..., help="the deployment under test, e.g. rc1-ai-campaign-performance"),
    database: str = typer.Option("sqlite", help="which adapter reaches your tables"),
    table: str = typer.Option("", help="the table holding the figures to check against"),
) -> None:
    """Write agent-evals.toml and make the log directory safe to write into."""

    root = root.resolve()
    existing = configuration.path_in(root)
    if existing.exists():
        typer.echo(f"{existing} already exists; edit it rather than re-running init.")
        raise typer.Exit(1)

    settings = configuration.Config(agent=agent, database=database, table=table)
    try:
        location = logging_directory.prepare(root, settings.logs)
    except logging_directory.LogsNotIgnored as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error

    written = configuration.save(root, settings)
    typer.echo(f"wrote {written}")
    typer.echo(f"logs  {location.path}  (ignored by git: {location.ignored})")
    typer.echo("next: agent-evals doctor")


@app.command()
def doctor(root: Path = typer.Option(Path("."), help="the agent's root directory")) -> None:
    """Check everything a run needs, and name what is missing rather than failing later."""

    root = root.resolve()
    # Three levels, not two. A missing table means figure checking is skipped, which is a real
    # configuration, not a fault -- and a checker that fails on things that are merely limited gets
    # ignored, which costs more than it saves.
    findings: list[tuple[str, str]] = []

    try:
        settings = configuration.load(root)
        findings.append(("ok", f"config: {configuration.FILENAME} names agent {settings.agent!r}"))
    except configuration.ConfigError as error:
        typer.echo(f"✗ {error}")
        raise typer.Exit(1) from error

    location = logging_directory.inspect_location(root / settings.logs)
    findings.append(
        (
            "ok" if location.safe else "fail",
            f"logs: {location.path} {'is ignored by git' if location.safe else 'WOULD BE COMMITTED'}",
        )
    )

    missing = [name for name in CREDENTIAL_VARIABLES.get(settings.database, ()) if not os.environ.get(name)]
    findings.append(
        (
            "ok" if not missing else "fail",
            f"credentials: {settings.database} "
            + ("reads the environment the agent uses" if not missing else f"needs {', '.join(missing)}"),
        )
    )

    findings.append(
        ("ok", f"table: {settings.table}")
        if settings.table
        else ("warn", "table: not set, so figures will not be checked against a database")
    )
    findings.append(_telemetry_finding())

    marks = {"ok": "✓", "warn": "!", "fail": "✗"}
    for level, line in findings:
        typer.echo(f"{marks[level]} {line}")
    if any(level == "fail" for level, _ in findings):
        raise typer.Exit(1)
    typer.echo("ready" + (" (with warnings)" if any(level == "warn" for level, _ in findings) else ""))


@app.command()
def mine(
    root: Path = typer.Option(Path("."), help="the agent's root directory"),
    days: int = typer.Option(0, help="how far back to look; you are asked if omitted"),
    limit: int = typer.Option(150, help="at most this many traces"),
    version: str = typer.Option("v1", help="the dataset version to write"),
) -> None:
    """Pull the questions people actually asked, and write them as a frozen dataset."""

    from ..mining import MinedQuestion, TraceQuery, build_dataset, build_manifest, open_source
    from ..mining.source import SourceNotInstalled
    from .telemetry import span

    settings = _loaded(root)
    traces = dict(settings.traces)
    source_name = str(traces.pop("source", "mlflow"))
    if not traces:
        typer.echo(f"nothing in [traces] of {configuration.FILENAME} says where to read them from.")
        raise typer.Exit(1)

    window = days or _chosen_window()
    logs = _prepared_logs(root, settings)

    try:
        source = open_source(source_name, traces)
    except (KeyError, SourceNotInstalled) as error:
        typer.echo(str(error))
        raise typer.Exit(1) from error

    async def read() -> list[MinedQuestion]:
        return await source(TraceQuery(since_days=window, limit=limit))

    with span("mine", source=source_name, since_days=window, limit=limit):
        questions = asyncio.run(read())

    if not questions:
        typer.echo(f"no questions found in the last {window} days. Widen the window or check [traces].")
        raise typer.Exit(1)

    dataset = build_dataset(questions, dataset_id=settings.agent, version=version)
    manifest = build_manifest(dataset)
    written = _write_dataset(logs, dataset, manifest)

    typer.echo(f"{len(questions)} traces read, {len(dataset.cases)} distinct questions")
    typer.echo(f"checksum {manifest.digest}")
    typer.echo(f"wrote    {written}")
    typer.echo("next: agent-evals draft")


WINDOWS = (90, 120, 180)


def _chosen_window() -> int:
    """Ask how far back to look. The three offered are the ones people actually pick."""

    typer.echo("How far back should it look?")
    for index, days in enumerate(WINDOWS, start=1):
        typer.echo(f"  {index}) {days} days")
    choice = typer.prompt("choose", default="1")
    try:
        return WINDOWS[int(choice) - 1]
    except (ValueError, IndexError):
        return int(choice)


def _loaded(root: Path) -> configuration.Config:
    try:
        return configuration.load(root.resolve())
    except configuration.ConfigError as error:
        typer.echo(str(error))
        raise typer.Exit(1) from error


def _prepared_logs(root: Path, settings: configuration.Config) -> Path:
    """The log directory, refusing to continue if git would commit what goes in it."""

    try:
        return logging_directory.prepare(root.resolve(), settings.logs).path
    except logging_directory.LogsNotIgnored as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error


def _write_dataset(logs: Path, dataset: Any, manifest: Any) -> Path:
    """Dataset and manifest as JSON, under the log directory because they hold customer questions."""

    path = logs / f"dataset-{dataset.version}.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": dataset.dataset_id,
                "version": dataset.version,
                "digest": manifest.digest,
                "cases": [
                    {"case_id": case.case_id, "inputs": dict(case.inputs), "source_trace_id": case.source_trace_id}
                    for case in dataset.cases
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return path


def _telemetry_finding() -> tuple[str, str]:
    """Importing the telemetry module is the check: it imports OpenTelemetry at the top."""

    try:
        import agent_evals.cli.telemetry  # noqa: F401
    except ImportError:
        return "fail", 'telemetry: OpenTelemetry missing. Install with: pip install "agent-evals[cli]"'
    return "ok", "telemetry: OpenTelemetry present; spans will be written to the log directory"


def main() -> None:  # pragma: no cover - the console-script entry point
    app()


__all__ = ["app", "main"]
