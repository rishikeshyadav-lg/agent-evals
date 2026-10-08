"""Turning mined questions into a dataset you can run twice and compare.

Two runs of the same window must produce the same dataset, or the checksum changes and every
comparison across time is meaningless. Traces come back in whatever order the backend felt like, and
the same question gets asked by different people on different days, so both have to be dealt with
here rather than hoped about.

So: duplicates collapse, order is fixed, and the identifier is derived from the question rather than
from the trace that happened to carry it. Mine the same window tomorrow and the only thing that
changes is what people genuinely asked in between.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Literal

from ..core.datasets import DatasetManifest
from ..core.evaluation import EvaluationCase, EvaluationDataset
from .source import MinedQuestion


def question_id(question: str) -> str:
    """A stable id for one question, from the question itself.

    Deriving it from the trace id would give the same question two ids when two people asked it, and
    would change the dataset every time the oldest trace fell out of the window.
    """

    return "q-" + hashlib.sha256(_normalized(question).encode()).hexdigest()[:12]


def _normalized(question: str) -> str:
    """Case and surrounding space ignored, so trivial variants count as the same question."""

    return " ".join(question.split()).casefold()


def deduplicate(questions: Sequence[MinedQuestion]) -> list[MinedQuestion]:
    """One entry per distinct question, keeping the earliest recorded occurrence.

    The earliest rather than the latest because it is the one that will still be there next time the
    window is mined; keeping the newest would change the dataset on every run.
    """

    by_id: dict[str, MinedQuestion] = {}
    for mined in questions:
        key = question_id(mined.question)
        kept = by_id.get(key)
        if kept is None or (mined.recorded_at and mined.recorded_at < kept.recorded_at):
            by_id[key] = mined
    return [by_id[key] for key in sorted(by_id)]


def build_dataset(
    questions: Sequence[MinedQuestion],
    *,
    dataset_id: str,
    version: str,
    classify: Callable[[MinedQuestion], str] | None = None,
) -> EvaluationDataset:
    """A frozen dataset of real questions, in an order that does not depend on the backend.

    `classify` is yours: what the categories are and which one a question belongs to is domain
    knowledge, and a library that guessed would be wrong in ways you could not see. Without it the
    source's own category is used, or none.
    """

    distinct = deduplicate(questions)
    if not distinct:
        raise ValueError("no questions were mined, so there is no dataset to build")
    cases = [
        EvaluationCase(
            question_id(mined.question),
            {
                "prompt": mined.question,
                # The A2A runner reads this; an in-process runner ignores it.
                "native_trace_id": mined.trace_id,
                "category": classify(mined) if classify else mined.category,
                "recorded_at": mined.recorded_at,
            },
            source_trace_id=mined.trace_id,
        )
        for mined in distinct
    ]
    return EvaluationDataset(dataset_id, version, cases)


def build_manifest(
    dataset: EvaluationDataset, *, suite: Literal["regression", "capability"] = "capability"
) -> DatasetManifest:
    """Freeze the dataset, so a later run can prove it is the same one."""

    return DatasetManifest.from_dataset(dataset, suite=suite)


__all__ = ["build_dataset", "build_manifest", "deduplicate", "question_id"]
