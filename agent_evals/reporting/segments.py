"""Per-segment scorecards, by slicing the run rather than reimplementing the scorecard.

Row labels — `category`, `pattern_key`, `set` — have been persisted since the run executor was
written and nothing has ever grouped by them. Segmenting today means filtering `RepeatedRun.rows` by
hand and rebuilding a `RepeatedRun`, which is both the right slice and the thing nobody does twice
the same way.

So this does exactly that slice and nothing else. Every existing reader — `build_scorecard`,
`operational_summary`, `case_scores`, `repeatability`, `suite_verdict` — already takes a
`RepeatedRun` and therefore already takes a segment. A segmented scorecard has to be the same
scorecard, or segments cannot be compared with each other or with the whole.

The label is read off the row and the labels are case properties, so every repeat of a case lands in
the same segment. That is what keeps the case-clustered bootstrap valid inside a segment: it
resamples whole cases, and a case split across two segments would be resampled as two.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from ..running.execution import RepeatedRun, RunRow
from ..scoring.operational import OperationalSummary, operational_summary
from .report import Scorecard, ScorecardMetrics, build_scorecard

SegmentLabel = Callable[[RunRow], str | None]
"""Which segment a row belongs to. None leaves the row out, and those rows are reported, not dropped."""


def by_category(row: RunRow) -> str | None:
    return row.category


def by_pattern_key(row: RunRow) -> str | None:
    return row.pattern_key


def by_set(row: RunRow) -> str | None:
    return row.set_name


def segment_run(run: RepeatedRun, label: SegmentLabel = by_category) -> dict[str, RepeatedRun]:
    """Slice a run into one `RepeatedRun` per segment, in the order the segments first appear.

    The slice keeps the run's own `settings` and the rows' original order, so `repeats` still reads
    true and results still come back in dataset order inside each segment.
    """

    grouped: dict[str, list[RunRow]] = {}
    for row in run.rows:
        name = label(row)
        if name is None:
            continue
        grouped.setdefault(name, []).append(row)
    return {name: RepeatedRun(settings=run.settings, rows=tuple(rows)) for name, rows in grouped.items()}


def unlabelled_rows(run: RepeatedRun, label: SegmentLabel = by_category) -> tuple[RunRow, ...]:
    """The rows the label left out, so a segmented report can say what it did not cover.

    Worth checking before reading a segmentation: `mining.build_dataset` writes `category` into case
    inputs and writes neither `pattern_key` nor `set`, so segmenting a mined dataset by pattern
    yields nothing until the caller sets them.
    """

    return tuple(row for row in run.rows if label(row) is None)


@dataclass(frozen=True, slots=True)
class Segment:
    """One segment's slice, and its scorecard when there was enough of it to build one honestly."""

    name: str
    runs: int
    cases: int
    scorecard: Scorecard | None
    operational: OperationalSummary | None
    reason: str | None = None


def segmented_scorecards(
    run: RepeatedRun,
    variant_id: str,
    *,
    label: SegmentLabel = by_category,
    minimum_cases: int = 3,
    metrics: ScorecardMetrics = ScorecardMetrics(),
    resamples: int = 2_000,
    seed: int = 0,
    include_error_messages: bool = False,
    unmeasured: Literal["fail", "exclude"] = "fail",
) -> dict[str, Segment]:
    """A scorecard and an operational summary per segment, built by the code the whole run uses.

    A segment under `minimum_cases` gets no scorecard and says why. The bootstrap resamples cases,
    so an interval over two of them carries no information, and printing one beside a real interval
    is how a segment nobody has evidence about gets acted on.

    A segment that raises on its own rows — an unmeasured-only slice, which `build_scorecard`
    refuses — is reported with that error as its reason rather than taking the whole report down.
    """

    segments: dict[str, Segment] = {}
    for name, slice_ in segment_run(run, label).items():
        rows = slice_.rows_for(variant_id)
        cases = len({row.case_id for row in rows})
        if not rows:
            continue
        if cases < minimum_cases:
            segments[name] = Segment(
                name=name,
                runs=len(rows),
                cases=cases,
                scorecard=None,
                operational=None,
                reason=f"only {cases} case(s); a bootstrap over that many carries no information",
            )
            continue
        try:
            scorecard = build_scorecard(
                slice_,
                variant_id,
                metrics=metrics,
                resamples=resamples,
                seed=seed,
                include_error_messages=include_error_messages,
                unmeasured=unmeasured,
            )
            summary = operational_summary(slice_, variant_id, resamples=resamples, seed=seed)
        except ValueError as error:
            segments[name] = Segment(
                name=name, runs=len(rows), cases=cases, scorecard=None, operational=None, reason=str(error)
            )
            continue
        segments[name] = Segment(
            name=name, runs=len(rows), cases=cases, scorecard=scorecard, operational=summary
        )
    return segments


def segment_sizes(run: RepeatedRun, label: SegmentLabel = by_category) -> Mapping[str, int]:
    """How many rows each segment holds, for deciding whether a segmentation is worth reading."""

    return {name: len(slice_.rows) for name, slice_ in segment_run(run, label).items()}


__all__ = [
    "Segment",
    "SegmentLabel",
    "by_category",
    "by_pattern_key",
    "by_set",
    "segment_run",
    "segment_sizes",
    "segmented_scorecards",
    "unlabelled_rows",
]
