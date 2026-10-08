"""The gate a generated query has to pass before anything is scored against it.

A wrong reference query and a wrong agent produce the identical report line: "it said 380, the table
says 400". So a draft nobody checked is worse than no draft, because it turns an unknown into a
confident number. This module exists to make that impossible by construction.

Two gates, in order. The first is mechanical and needs no person: run the query and reject anything
that cannot be ground truth — it raised, it returned nothing, it returned more than one row, it is
missing a field, or a field is not a finite number. The second is a person, and it is the one that
catches a query that runs perfectly and answers the wrong question.

A draft cannot be approved without the row it returned. That is not a convention here, it is the
signature: `approve` takes a verified check, and a check only holds a row when running it produced
exactly one. Showing the SQL alone invites a reviewer to nod at plausible-looking syntax.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

Status = Literal["drafted", "verified", "rejected", "approved"]


@dataclass(frozen=True, slots=True)
class DraftCheck:
    """What happened when the draft was actually run.

    `row` is present only when the query returned exactly one, which is also the only case a draft
    can be approved from. Everything else carries the reason instead.
    """

    rows: int = 0
    columns: tuple[str, ...] = ()
    row: Mapping[str, Any] | None = None
    refusal: str = ""

    @property
    def usable(self) -> bool:
        return self.row is not None and not self.refusal


def verify(sql_rows: Sequence[Mapping[str, Any]], fields: Mapping[str, str]) -> DraftCheck:
    """Decide whether what the query returned could be ground truth at all.

    Every refusal is named, because "rejected" on its own tells the author nothing about which part
    of their query to change.
    """

    columns = tuple(sql_rows[0]) if sql_rows else ()
    if not sql_rows:
        return DraftCheck(rows=0, refusal="the query returned no rows, so there is nothing to compare against")
    if len(sql_rows) > 1:
        return DraftCheck(
            rows=len(sql_rows),
            columns=columns,
            refusal=f"the query returned {len(sql_rows)} rows; which one is the answer is not for a tool to guess",
        )
    row = sql_rows[0]
    missing = sorted(name for name in fields if name not in row)
    if missing:
        return DraftCheck(rows=1, columns=columns, refusal=f"the query returns no column for {', '.join(missing)}")
    unusable = sorted(name for name in fields if not _finite(row[name]))
    if unusable and len(unusable) == len(fields):
        # An aggregate over no matching rows returns one row of nulls, not zero rows. Reporting that
        # as bad data sends the author to the columns when the real fault is the filter.
        return DraftCheck(
            rows=1,
            columns=columns,
            refusal="every figure came back empty, so the query's filter matched nothing",
        )
    if unusable:
        return DraftCheck(rows=1, columns=columns, refusal=f"{', '.join(unusable)} is not a finite number")
    return DraftCheck(rows=1, columns=columns, row=dict(row))


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


@dataclass(frozen=True, slots=True)
class Draft:
    """One generated query, what running it showed, and whether a person accepted it."""

    case_id: str
    question: str
    sql: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    fields: Mapping[str, str] = field(default_factory=dict)
    required: Sequence[str] = ()
    status: Status = "drafted"
    check: DraftCheck = field(default_factory=DraftCheck)
    note: str = ""

    def checked(self, check: DraftCheck) -> Draft:
        """The draft after running it: verified when it could be ground truth, rejected when not."""

        status: Status = "verified" if check.usable else "rejected"
        return replace(self, check=check, status=status, note=check.refusal)

    def approve(self, note: str = "") -> Draft:
        """Accept this query as ground truth. Only possible once it has been run and seen.

        The guard is the point of the module. A reviewer who has not been shown the row the query
        returns is reviewing syntax, and syntax is not what goes wrong here.
        """

        if not self.check.usable:
            raise ValueError(
                f"{self.case_id} cannot be approved: {self.check.refusal or 'it has not been run yet'}"
            )
        return replace(self, status="approved", note=note)

    def reject(self, note: str) -> Draft:
        if not note.strip():
            raise ValueError("rejecting a draft needs a reason, so the next attempt can be different")
        return replace(self, status="rejected", note=note)

    @property
    def scoreable(self) -> bool:
        """Only an approved draft becomes a case. Verified is not enough; a person has to have said so."""

        return self.status == "approved"


def reference_for(draft: Draft) -> dict[str, Any]:
    """The draft as the `expected["reference"]` block `SqlReference` reads."""

    if not draft.scoreable:
        raise ValueError(f"{draft.case_id} is {draft.status}, and only an approved draft can be scored against")
    return {
        "sql": draft.sql,
        "parameters": dict(draft.parameters),
        "fields": dict(draft.fields),
        "required": list(draft.required),
    }


__all__ = ["Draft", "DraftCheck", "Status", "reference_for", "verify"]
