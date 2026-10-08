"""Writing the one file a project has to own, filled in rather than left blank.

Deciding what a question means is the project's job, not this package's, so a drafter has to live in
the project. That is a reason for it to be yours, not a reason to hand you an empty file and a
documentation link.

So the scaffold is a working drafter for the shape that dominates real traffic -- "how is <id>
doing" -- with the table name already filled in and the metrics named. It runs as written. What it
needs from you is the part only you know: whether those are the right columns, and whether the
pattern matches how your users name things.
"""

from __future__ import annotations

from pathlib import Path

FILENAME = "eval_drafter.py"

# The metrics most delivery tables carry, as column -> the word to look for in prose. A starting
# point to edit, not a claim about your schema.
SUGGESTED_METRICS: tuple[tuple[str, str], ...] = (
    ("spend", "spent"),
    ("clicks", "clicks"),
    ("impressions", "impressions"),
)

TEMPLATE = '''"""How this project turns a question into the query that settles it.

`agent-evals init` wrote this from the table it found. Two things are yours to check:

  1. the columns below are the ones your table actually has, and the words beside them are what
     your agent writes in prose ("spent", not "spend");
  2. the pattern matches how your users name the thing they are asking about.

A question the pattern does not match gets no draft at all, which is deliberate: a drafter that
always produces something produces nonsense for the questions it does not understand.
"""

from agent_evals.drafting import TemplateDrafter

TABLE = {table!r}

# column in your table -> the word to look for in the agent's answer
METRICS = {metrics}

DRAFTER = TemplateDrafter(
    sql=(
        "SELECT " + ", ".join(f"SUM(`{{column}}`) AS {{column}}" for column in METRICS) + " "
        f"FROM {{TABLE}} WHERE `{identifier}` = :{identifier}"
    ),
    # Whatever identifies the thing being asked about. This matches a six-digit id.
    pattern=r"\\b(\\d{{6}})\\b",
    parameter={identifier!r},
    fields=METRICS,
    # Empty means "check whatever figures the answer states, require none of them". Right for an
    # open question; name the columns here when the question asks for specific metrics.
    required=[],
)
'''


def write_drafter(root: Path, table: str, identifier: str = "acid") -> Path | None:
    """Write a runnable drafter for this project, or nothing when there is no table to query.

    Never overwrites: the drafter is the file most likely to have been edited, and silently
    replacing someone's pattern would undo the only part they had to think about.
    """

    if not table.strip():
        return None
    path = root / FILENAME
    if path.exists():
        return path
    metrics = "{\n" + "".join(f'    "{column}": "{word}",\n' for column, word in SUGGESTED_METRICS) + "}"
    path.write_text(TEMPLATE.format(table=table, metrics=metrics, identifier=identifier))
    return path


__all__ = ["FILENAME", "SUGGESTED_METRICS", "write_drafter"]
