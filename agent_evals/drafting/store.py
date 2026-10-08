"""Keeping drafts on disk between `draft` and `review`.

Reviewing a batch of queries is slow and human, so it has to survive being interrupted. Drafts are
written as one JSON file holding every draft and its verdict: approve three today, the rest
tomorrow, and nothing already decided is asked about twice.

The file holds the questions people asked, so it lives under the log directory the tool already
refuses to write anywhere git would commit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .review import Draft, DraftCheck

FILENAME = "drafts.json"


def path_in(logs: Path) -> Path:
    return logs / FILENAME


def load(logs: Path) -> dict[str, Draft]:
    """Every draft decided so far, by case id. An absent file means none."""

    path = path_in(logs)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {case_id: _draft(case_id, entry) for case_id, entry in raw.items()}


def save(logs: Path, drafts: Mapping[str, Draft]) -> Path:
    """Write every draft, ordered by case id so the file does not churn between runs."""

    path = path_in(logs)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {case_id: _record(drafts[case_id]) for case_id in sorted(drafts)}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def merge(existing: Mapping[str, Draft], drafted: Sequence[Draft]) -> dict[str, Draft]:
    """Add new drafts without disturbing decisions already made.

    A second `draft` run must not quietly replace an approval with a fresh unreviewed query; that
    would undo review silently, which is the one thing this whole stage exists to prevent.
    """

    merged = dict(existing)
    for draft in drafted:
        if draft.case_id not in merged:
            merged[draft.case_id] = draft
    return merged


def _record(draft: Draft) -> dict[str, Any]:
    return {
        "question": draft.question,
        "sql": draft.sql,
        "parameters": dict(draft.parameters),
        "fields": dict(draft.fields),
        "required": list(draft.required),
        "status": draft.status,
        "note": draft.note,
        "check": {
            "rows": draft.check.rows,
            "columns": list(draft.check.columns),
            "row": dict(draft.check.row) if draft.check.row else None,
            "refusal": draft.check.refusal,
        },
    }


def _draft(case_id: str, entry: Mapping[str, Any]) -> Draft:
    check = entry.get("check") or {}
    return Draft(
        case_id=case_id,
        question=entry["question"],
        sql=entry["sql"],
        parameters=entry.get("parameters") or {},
        fields=entry.get("fields") or {},
        required=entry.get("required") or [],
        status=entry.get("status", "drafted"),
        note=entry.get("note", ""),
        check=DraftCheck(
            rows=check.get("rows", 0),
            columns=tuple(check.get("columns") or ()),
            row=check.get("row"),
            refusal=check.get("refusal", ""),
        ),
    )


__all__ = ["FILENAME", "load", "merge", "path_in", "save"]
