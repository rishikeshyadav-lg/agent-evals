"""Asking a model which figure an answer actually stated, instead of parsing for it.

Distance-based extraction works on a sentence and falls over on a document. In a real answer —
a totals table, a weekly breakdown, a placement breakdown and six paragraphs of commentary — the
word "clicks" appears many times, and the figure nearest to it is as often a weekly detail as the
campaign total. Measured on three real answers the parser read nine of twelve figures correctly,
which is a poor foundation for a check whose whole job is numbers.

A model does not have that problem. It reads `| Clicks | 173 |` as the total and
"peaked in Week 1 (132 clicks)" as a detail, which is a judgement about meaning rather than
proximity.

**It is given the true figure and asked to verify, never to extract.** "The table says 173 — does
this answer state that as the campaign total?" is a question with a right answer that can be checked
later. "What clicks did this answer state?" invites a number to be invented, and an invented figure
here would be indistinguishable from the agent having stated it.

What this costs: a model call per case, and determinism. The same answer can be judged differently
tomorrow. `extra["figures"]` is preferred over both this and the parser wherever an agent can supply
it, because a figure handed over as data needs neither reading nor judging.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.evaluation import _await_value
from .judging import JudgeClient

logger = logging.getLogger(__name__)

PROMPT = """You are checking whether an analyst's summary states particular figures correctly.

Their answer:
---
{answer}
---

For each metric below you are given the true value from the source table. Decide whether the answer
states that metric's **overall total** as that value. Ignore per-week, per-placement and other
breakdown figures: only the overall total for the whole campaign counts.

{expected}

Reply with only JSON: {{"<metric>": {{"stated": true|false, "value": <the number the answer gives as
the overall total, or null if it gives none>}}, ...}} with one entry per metric above."""


@dataclass(frozen=True, slots=True)
class JudgeClaims:
    """Reads what an answer claimed for each field by asking a model, given the true values.

    Pass it to `SqlReference(claims_of=...)`. It replaces the reading of the answer, not the
    checking: the truth still comes from your own query, and the comparison is still arithmetic.
    """

    client: JudgeClient
    name: str = "figure_judge"

    async def __call__(
        self, answer: str, fields: Mapping[str, str], truth: Mapping[str, float]
    ) -> Mapping[str, float | None]:
        if not answer.strip() or not truth:
            return {}
        expected = "\n".join(
            f"- {label} (metric id {name}): true value {truth[name]}" for name, label in fields.items()
        )
        try:
            reply = await _await_value(self.client(PROMPT.format(answer=answer, expected=expected)))
        except Exception:  # noqa: BLE001 -- an unreachable judge read nothing, and says so by returning nothing
            logger.info("The figure judge raised", exc_info=True)
            raise

        decoded = _decoded(str(reply))
        if decoded is None:
            raise ValueError("the figure judge's reply could not be read as JSON")
        claimed: dict[str, float | None] = {}
        for name in fields:
            entry = decoded.get(name)
            if not isinstance(entry, Mapping) or not entry.get("stated"):
                continue
            value = entry.get("value")
            # A judge that says "stated" without a number has not told us what was stated, and
            # treating that as agreement would let it wave figures through unseen.
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                claimed[name] = float(value)
        return claimed


def _decoded(reply: str) -> Mapping[str, Any] | None:
    start = reply.find("{")
    if start < 0:
        return None
    try:
        decoded, _ = json.JSONDecoder().raw_decode(reply[start:])
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None





ROWS_PROMPT = """You are checking whether an analyst's report states particular rows correctly.

Their answer:
---
{answer}
---

Below is one row per {dimension}, with the true values from the source table. For each one, report
the figures the answer gives for that {dimension}. Match a row by its {dimension} label, not by its
position. If the answer does not break the data down by that {dimension} at all, or omits that
particular one, leave it out of your reply entirely.

{expected}

Reply with only JSON: {{"<label>": {{"<metric id>": <the number the answer gives for it, or null>}},
...}} with one entry per {dimension} the answer actually states."""


@dataclass(frozen=True, slots=True)
class JudgeRows:
    """Reads what an answer stated for each key of a breakdown, by asking a model.

    Pass it to `SqlBreakdown(read_rows=...)`. There is no proximity-based alternative on purpose: a
    breakdown multiplies the failure that made distance-based reading unusable on one row, because a
    metric's name appears once per row and the figure nearest it belongs to whichever row the model
    laid out closest.
    """

    client: JudgeClient
    dimension: str = "row"
    name: str = "row_judge"

    async def __call__(
        self,
        answer: str,
        fields: Mapping[str, str],
        truth: Mapping[str, Mapping[str, float]],
    ) -> Mapping[str, Mapping[str, float | None]]:
        if not answer.strip() or not truth:
            return {}
        expected = "\n".join(
            f"- {key}: " + ", ".join(f"{name} (metric id {name}) {values.get(name)}" for name in fields)
            for key, values in truth.items()
        )
        prompt = ROWS_PROMPT.format(answer=answer, dimension=self.dimension, expected=expected)
        try:
            reply = await _await_value(self.client(prompt))
        except Exception:  # noqa: BLE001 -- an unreachable judge read nothing, and the caller says so
            logger.info("The row judge raised", exc_info=True)
            raise

        decoded = _decoded(str(reply))
        if decoded is None:
            raise ValueError("the row judge's reply could not be read as JSON")
        stated: dict[str, Mapping[str, float | None]] = {}
        for key in truth:
            entry = decoded.get(key)
            if not isinstance(entry, Mapping):
                continue
            row: dict[str, float | None] = {}
            for name in fields:
                value = entry.get(name)
                row[name] = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            # A key the judge answered with no readable figure at all is a key it did not state.
            if any(value is not None for value in row.values()):
                stated[key] = row
        return stated


__all__ = ["PROMPT", "ROWS_PROMPT", "JudgeClaims", "JudgeRows"]
