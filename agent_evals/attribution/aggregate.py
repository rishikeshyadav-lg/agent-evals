"""What went wrong across a whole run, ranked, with the cases named.

Codes are named rather than counted alone, because the first useful thing to do with "fabrication
explains 7 runs" is open one of them. A count with no case ids is a number nobody can check.

Causes that are gaps in our own measurement are reported beside the ranking and never in it. Letting
them rank would put the loudest number in the report on something the agent did not do.
"""

from __future__ import annotations

import collections
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..running.execution import RepeatedRun
from .causes import RUBRIC, Attribution


@dataclass(frozen=True, slots=True)
class CodeCount:
    """How often one code was seen, and in which cases."""

    code: str
    runs: int
    cases: Sequence[str]


@dataclass(frozen=True, slots=True)
class CauseReport:
    """Every attributed cause across one variant's runs, ranked by how many runs it explains."""

    variant_id: str
    runs: int
    bad_runs: int
    attributed_runs: int
    blamed_on_measurement: int
    counts: Sequence[CodeCount]
    runner_up_counts: Sequence[CodeCount]
    unattributed: Sequence[tuple[str, int, str]]

    @property
    def dominant(self) -> CodeCount | None:
        """The cause behind the most runs, or None when nothing was attributed."""

        return self.counts[0] if self.counts else None


def _counted(pairs: Sequence[tuple[str, str]]) -> tuple[CodeCount, ...]:
    """Codes ranked by the runs they explain, ties broken by code name so two reports agree."""

    runs: collections.Counter[str] = collections.Counter()
    cases: dict[str, list[str]] = collections.defaultdict(list)
    for code, case_id in pairs:
        runs[code] += 1
        if case_id not in cases[code]:
            cases[code].append(case_id)
    return tuple(
        CodeCount(code=code, runs=count, cases=tuple(cases[code]))
        for code, count in sorted(runs.items(), key=lambda item: (-item[1], item[0]))
    )


def cause_report(attributions: Sequence[Attribution], variant_id: str, *, runs: int) -> CauseReport:
    """Rank the causes of one variant's bad runs."""

    bad = [a for a in attributions if a.cause is not None or not a.attributable]
    agent_faults = [(a.cause.code, a.case_id) for a in attributions if a.cause is not None and a.cause.blames_agent]
    measurement = [a for a in attributions if a.cause is not None and not a.cause.blames_agent]
    runners_up = [(cause.code, a.case_id) for a in attributions for cause in a.also]
    return CauseReport(
        variant_id=variant_id,
        runs=runs,
        bad_runs=len(bad),
        attributed_runs=len([a for a in attributions if a.cause is not None]),
        blamed_on_measurement=len(measurement),
        counts=_counted(agent_faults),
        runner_up_counts=_counted(runners_up),
        unattributed=tuple(
            (a.case_id, a.repeat, a.reason or "no reason recorded") for a in attributions if not a.attributable
        ),
    )


@dataclass(frozen=True, slots=True)
class FailureCodeReport:
    """Every failure code a rubric raised, and every criterion that went unmeasured.

    Two lists because they are two different findings. A code is a verdict about an answer; an
    unmeasured criterion is a verdict about us, and the same report has to carry both or a short list
    of codes reads as a short list of problems.
    """

    variant_id: str
    runs: int
    runs_with_codes: int
    counts: Sequence[CodeCount]
    unmeasured: Sequence[CodeCount]


def failure_code_report(run: RepeatedRun, variant_id: str, *, rubric: str = RUBRIC) -> FailureCodeReport:
    """Count the rubric's failure codes and unmeasured criteria over one variant's rows.

    Reads both `score_details[rubric]["failure_codes"]` and `score_details[rubric + ".measured"]`
    and unions them per row: the first exists only when a headline was produced, and the rubric
    gathers codes before deciding whether to withhold one, precisely so a fabricated figure is still
    recorded on the runs where nothing else could be scored.
    """

    rows = [row for row in run.rows if row.variant_id == variant_id]
    if not rows:
        raise ValueError(f"the run has no rows for variant {variant_id!r}")

    code_pairs: list[tuple[str, str]] = []
    unmeasured_pairs: list[tuple[str, str]] = []
    with_codes = 0
    for row in rows:
        details = row.result.score_details
        found: set[str] = set()
        for name in (rubric, f"{rubric}.measured"):
            detail = details.get(name)
            if not isinstance(detail, Mapping):
                continue
            raw = detail.get("failure_codes")
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                found.update(str(code) for code in raw)
        if found:
            with_codes += 1
        code_pairs.extend((code, row.case_id) for code in sorted(found))

        measured = details.get(f"{rubric}.measured")
        if isinstance(measured, Mapping):
            gaps = measured.get("unmeasured")
            if isinstance(gaps, Mapping):
                unmeasured_pairs.extend((str(name), row.case_id) for name in sorted(gaps))

    return FailureCodeReport(
        variant_id=variant_id,
        runs=len(rows),
        runs_with_codes=with_codes,
        counts=_counted(code_pairs),
        unmeasured=_counted(unmeasured_pairs),
    )


__all__ = ["CauseReport", "CodeCount", "FailureCodeReport", "cause_report", "failure_code_report"]
