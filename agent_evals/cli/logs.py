"""Where a run writes its logs, and the check that stops them reaching a commit.

Logs hold the questions users asked and the answers an agent gave. That is customer text, and the
directory sits inside the agent's own repository, so one `git add -A` would commit it. The guard here
exists because the convenient location and the safe one are not the same place, and the convenient one
was chosen deliberately.

So nothing is written until git confirms the directory is ignored. A missing `.gitignore` entry, or an
edited one, stops the run with the line to add rather than quietly staging customer text.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DIRECTORY = "eval-logs"


class LogsNotIgnored(RuntimeError):
    """The log directory would be committed. Raised before anything is written."""


@dataclass(frozen=True, slots=True)
class LogLocation:
    """A directory for one tool's logs, and whether git would keep its contents out of a commit."""

    path: Path
    inside_repository: bool
    ignored: bool

    @property
    def safe(self) -> bool:
        """Outside a repository there is nothing to commit into, so only a tracked path can be unsafe."""

        return self.ignored or not self.inside_repository

    def require_safe(self) -> None:
        if self.safe:
            return
        raise LogsNotIgnored(
            f"{self.path} is inside a git repository and is not ignored, so its logs would be "
            f"committed. They contain the questions users asked. Add this line to .gitignore:\n"
            f"    {self.path.name}/"
        )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=10
    )


def inspect_location(path: Path) -> LogLocation:
    """Ask git whether this directory's contents would be committed.

    `check-ignore` is the authority rather than reading `.gitignore` ourselves: the rules compose
    across the repository's file, the user's global one and `.git/info/exclude`, and re-implementing
    that is how a guard ends up disagreeing with the tool it is guarding against.
    """

    root = path.parent
    inside = _inside_repository(root)
    if not inside:
        return LogLocation(path=path, inside_repository=False, ignored=False)
    # A directory git has never seen needs a trailing name to match a `dir/` rule, so ask about a
    # file that would live inside it rather than the directory itself.
    probe = _git(root, "check-ignore", "-q", str(path / "probe.jsonl"))
    return LogLocation(path=path, inside_repository=True, ignored=probe.returncode == 0)


def prepare(root: Path, directory: str = DEFAULT_DIRECTORY) -> LogLocation:
    """Create the log directory and make it ignored, then confirm git agrees.

    Two layers, because the root `.gitignore` is a shared file somebody else may rewrite: the entry
    goes there, and the directory also carries its own `.gitignore` holding `*`, which keeps it
    ignored on its own if the root entry is ever lost.
    """

    path = root / directory
    path.mkdir(parents=True, exist_ok=True)

    # Order matters. Writing the inner file first makes the directory ignored immediately, so a
    # "only add the root entry if still unsafe" check passes and never adds it -- leaving one layer
    # where two were promised. The root entry goes in unconditionally.
    if _inside_repository(root):
        _add_root_entry(root, directory)
    (path / ".gitignore").write_text("*\n")

    location = inspect_location(path)
    location.require_safe()
    return location


def _inside_repository(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"


def _add_root_entry(root: Path, directory: str) -> None:
    """Append `directory/` to the repository's .gitignore, leaving whatever is already there."""

    ignore_file = root / ".gitignore"
    existing = ignore_file.read_text() if ignore_file.exists() else ""
    if any(line.strip() in {directory, f"{directory}/"} for line in existing.splitlines()):
        return
    separator = "" if existing.endswith("\n") or not existing else "\n"
    ignore_file.write_text(f"{existing}{separator}{directory}/\n")


__all__ = ["DEFAULT_DIRECTORY", "LogLocation", "LogsNotIgnored", "inspect_location", "prepare"]
