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
import sys
from collections.abc import Awaitable
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
    yes: bool = typer.Option(False, "--yes", "-y", help="accept every detected default without asking"),
    agent: str = typer.Option("", help="name the deployment yourself, when detection finds none"),
) -> None:
    """Set up this project by reading what it already records, asking only what cannot be found."""

    from .detect import detect, host_for_profile
    from .scaffold import write_drafter

    root = root.resolve()
    if configuration.path_in(root).exists():
        typer.echo(f"{configuration.FILENAME} already exists; edit it rather than re-running init.")
        raise typer.Exit(1)

    typer.echo("Looking around…")
    found = detect(root)
    _report(found)

    deployment = _pick_deployment(found.deployments, yes)
    profile = _pick(found.profiles, "Authenticate with", yes)
    table = deployment.get("table") if deployment else found.shared.get("table", "")

    name = agent or (deployment.name if deployment else "")
    if not name:
        # Never prompt under --yes, and never hang in a script. Say what to pass instead.
        if yes or not _interactive():
            typer.echo("no deployment found in this project. Name one with --agent <name>.")
            raise typer.Exit(1)
        name = typer.prompt("Which deployment are you evaluating?")

    settings = configuration.Config(
        agent=name,
        database="databricks" if deployment and deployment.get("warehouse_id") else "sqlite",
        database_settings=_database_settings(deployment, profile),
        table=table,
        drafter="eval_drafter:DRAFTER",
        traces=_trace_settings(deployment),
    )

    try:
        location = logging_directory.prepare(root, settings.logs)
    except logging_directory.LogsNotIgnored as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error

    written = configuration.save(root, settings)
    drafter_path = write_drafter(root, table)

    typer.echo("")
    typer.echo(f"  created  {written.name}")
    typer.echo(f"  created  {drafter_path.name}" if drafter_path else "  skipped  drafter (no table detected)")
    typer.echo(f"  ignored  {location.path.name}/  (added to .gitignore)")
    if profile:
        typer.echo(f"  auth     profile {profile} -> {host_for_profile(profile) or 'no host recorded'}")
    typer.echo("")
    typer.echo("Next:  agent-evals doctor")


def _interactive() -> bool:
    """Whether there is someone there to answer. A script must fail, not wait."""

    return sys.stdin.isatty()


def _report(found: Any) -> None:
    """Say what was found and where, so a wrong guess is visible before it is accepted."""

    for deployment in found.deployments:
        typer.echo(f"  found  {deployment.name:34} {len(deployment.settings)} settings in {deployment.source}")
    if found.profiles:
        typer.echo(f"  found  {len(found.profiles)} Databricks profile(s): {', '.join(found.profiles)}")
    if not found.deployments and not found.profiles:
        typer.echo("  found  nothing to go on; you will be asked for everything")


def _pick_deployment(deployments: Any, yes: bool) -> Any:
    if not deployments:
        return None
    names = [d.name for d in deployments]
    chosen = _pick(names, "Which deployment are you evaluating", yes)
    return next(d for d in deployments if d.name == chosen)


def _pick(options: Any, question: str, yes: bool) -> str:
    """One choice from what was found. The first is the default, so Enter is always an answer."""

    options = list(options)
    if not options:
        return ""
    if len(options) == 1 or yes:
        return str(options[0])
    typer.echo("")
    for index, option in enumerate(options, start=1):
        typer.echo(f"    {index}) {option}")
    answer = typer.prompt(f"{question}?", default="1")
    try:
        return str(options[int(answer) - 1])
    except (ValueError, IndexError):
        return str(answer)


def _database_settings(deployment: Any, profile: str) -> dict[str, str]:
    """Everything the warehouse client needs, including the profile so nobody exports a host."""

    if deployment is None:
        return {}
    settings = {key: deployment.get(key) for key in ("warehouse_id", "catalog", "schema") if deployment.get(key)}
    if profile:
        settings["profile"] = profile
    return settings


def _trace_settings(deployment: Any) -> dict[str, str]:
    if deployment is None or not deployment.get("experiment_id"):
        return {}
    return {"source": "mlflow", "experiment_id": deployment.get("experiment_id")}


@app.command()
def doctor(root: Path = typer.Option(Path("."), help="the agent's root directory")) -> None:
    """Check everything a run needs, and name what is missing rather than failing later."""

    root = root.resolve()
    # Three levels, not two. A missing table means figure checking is skipped, which is a real
    # configuration, not a fault -- and a checker that fails on things that are merely limited gets
    # ignored, which costs more than it saves.
    findings: list[tuple[str, str]] = []

    settings = _loaded(root)
    findings.append(("ok", f"config: {configuration.FILENAME} names agent {settings.agent!r}"))

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


def _apply_profile(settings: configuration.Config) -> None:
    """Set the environment a Databricks client expects, from the profile init recorded.

    The agent's own client reads DATABRICKS_HOST and never looks at ~/.databrickscfg, so without
    this every command would need two exports first. The profile is already on the machine; asking
    someone to restate it in their shell is asking them to copy their own configuration.
    """

    profile = str(settings.database_settings.get("profile") or "")
    if not profile:
        return
    from .detect import host_for_profile

    os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", profile)
    host = host_for_profile(profile)
    if host:
        os.environ.setdefault("DATABRICKS_HOST", host)


def _loaded(root: Path) -> configuration.Config:
    try:
        settings = configuration.load(root.resolve())
    except configuration.ConfigError as error:
        typer.echo(str(error))
        raise typer.Exit(1) from error
    _apply_profile(settings)
    return settings


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


@app.command()
def draft(
    root: Path = typer.Option(Path("."), help="the agent's root directory"),
    version: str = typer.Option("v1", help="which mined dataset to draft for"),
) -> None:
    """Propose a reference query for each mined question, run it, and set aside the ones that fail."""

    from ..drafting import store, verify
    from .drafters import load_drafter
    from .telemetry import span

    settings = _loaded(root)
    logs = _prepared_logs(root, settings)
    questions = _mined_questions(logs, version)
    drafter = load_drafter(root, settings)
    if drafter is None:
        typer.echo("no drafter configured. Add [drafting] to agent-evals.toml naming a module:attribute.")
        raise typer.Exit(1)

    execute = _executor(settings)
    existing = store.load(logs)
    fresh = [q for q in questions if q.trace_id not in existing]
    typer.echo(f"{len(questions)} questions, {len(existing)} already decided, {len(fresh)} to draft")

    drafted = []
    for question in fresh:
        with span("draft", case_id=question.trace_id):
            proposal = asyncio.run(_drafted(drafter, question))
        if proposal is None:
            continue
        rows, failure = asyncio.run(_ran(execute, proposal))
        drafted.append(proposal.reject(failure) if failure else proposal.checked(verify(rows, proposal.fields)))

    merged = store.merge(existing, drafted)
    written = store.save(logs, merged)
    verified = sum(1 for d in merged.values() if d.status == "verified")
    rejected = sum(1 for d in merged.values() if d.status == "rejected")
    typer.echo(f"{len(drafted)} drafted: {verified} ready for review, {rejected} rejected before you see them")
    typer.echo(f"wrote {written}")
    typer.echo("next: agent-evals review")


@app.command()
def review(
    root: Path = typer.Option(Path("."), help="the agent's root directory"),
    limit: int = typer.Option(0, help="review at most this many; all of them by default"),
) -> None:
    """Show each verified query and the row it returned, and record what you decide."""

    from ..drafting import store

    settings = _loaded(root)
    logs = _prepared_logs(root, settings)
    drafts = store.load(logs)
    waiting = [d for d in drafts.values() if d.status == "verified"]
    if not waiting:
        typer.echo("nothing waiting for review. Run `agent-evals draft` first.")
        raise typer.Exit(0 if drafts else 1)

    for draft_item in waiting[: limit or len(waiting)]:
        _show(draft_item)
        answer = typer.prompt("approve? [y/n/s=skip]", default="s").strip().lower()
        if answer.startswith("y"):
            drafts[draft_item.case_id] = draft_item.approve()
        elif answer.startswith("n"):
            drafts[draft_item.case_id] = draft_item.reject(typer.prompt("why"))

    store.save(logs, drafts)
    approved = sum(1 for d in drafts.values() if d.scoreable)
    typer.echo(f"{approved} approved and ready to score")
    typer.echo("next: agent-evals run")


def _show(draft_item: Any) -> None:
    """The question, the query, and the row it returned.

    The row is the point. A reviewer shown only SQL checks that it parses; the failure that matters
    is a query that runs perfectly and answers a different question than the one asked.
    """

    typer.echo("")
    typer.echo(f"  case     {draft_item.case_id}")
    typer.echo(f"  question {draft_item.question}")
    typer.echo(f"  sql      {draft_item.sql}")
    typer.echo(f"  params   {dict(draft_item.parameters)}")
    typer.echo(f"  RETURNED {dict(draft_item.check.row or {})}")


async def _drafted(drafter: Any, question: Any) -> Any:
    proposal = drafter(question)
    return await proposal if isinstance(proposal, Awaitable) else proposal


async def _ran(execute: Any, proposal: Any) -> tuple[list[dict[str, Any]], str]:
    """Run the draft. A query that raises is the drafter's failure, not the database's."""

    try:
        return await execute(proposal.sql, dict(proposal.parameters)), ""
    except Exception as error:  # noqa: BLE001 -- any failure here means this draft cannot be used
        return [], f"the query failed: {type(error).__name__}: {error}"


def _executor(settings: configuration.Config) -> Any:
    """The database client, with `profile` removed: it configures the environment, not the client."""

    from ..sql import open_executor

    options = {k: v for k, v in settings.database_settings.items() if k != "profile"}
    return open_executor(settings.database, options)


def _mined_questions(logs: Path, version: str) -> list[Any]:
    from ..mining import MinedQuestion

    path = logs / f"dataset-{version}.json"
    if not path.exists():
        typer.echo(f"no mined dataset at {path}. Run `agent-evals mine` first.")
        raise typer.Exit(1)
    cases = json.loads(path.read_text())["cases"]
    return [
        MinedQuestion(
            question=case["inputs"]["prompt"],
            trace_id=case["source_trace_id"] or case["case_id"],
            recorded_at=case["inputs"].get("recorded_at", ""),
            category=case["inputs"].get("category", ""),
        )
        for case in cases
    ]


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
