"""Where one run's time and money went, read from the `llm_usage` envelope.

Measured on one deployment: 7,986s of 9,435s wall-clock was LLM time across 150 runs, and $0.651
per run came almost entirely from a mean 203,190 **input** tokens. Both are attributable per
`client_role`, and neither is visible in the p95 the scorecard reports — a latency number nobody can
split tells you to be faster and not what to make faster.

Every number here is None when the envelope did not carry it, never zero. A run recorded before the
envelope existed would otherwise report a 0% LLM share, which reads as "the model is not the
problem" and is the opposite of what is known. `attributable` is the single flag that says which it
is, and partial is reported field by field rather than collapsed.
"""

from __future__ import annotations

import collections
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..running.execution import RepeatedRun, RunRow


def _number(value: Any) -> float | None:
    """A finite non-negative number, or None. Strings and negatives are not usage, they are noise."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        return None
    return number


def _count(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


@dataclass(frozen=True, slots=True)
class RoleUsage:
    """What one `client_role` spent, over the calls that reported it."""

    role: str
    calls: int
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    calls_missing_tokens: int = 0


@dataclass(frozen=True, slots=True)
class UsageAttribution:
    """One run's time and spend, split into the model's share and what the envelope would not say.

    `llm_share` may exceed 1.0 and is deliberately not clamped: concurrent calls really do sum past
    the wall clock, and a silently clamped 1.0 is a fact destroyed rather than a fact reported.
    `notes` says so instead. `tokens_complete` False means `input_tokens` is a floor, because fewer
    calls reported token counts than were made.
    """

    case_id: str
    variant_id: str
    repeat: int
    attributable: bool
    reason: str | None
    wall_clock_ms: float | None
    llm_latency_ms: float | None
    llm_share: float | None
    llm_calls: int | None
    failed_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    tokens_complete: bool | None
    llm_cost_usd: float | None
    run_cost_usd: float | None
    llm_cost_share: float | None
    tool_calls: int = 0
    by_role: Mapping[str, RoleUsage] = field(default_factory=dict)
    notes: Sequence[str] = ()


def usage_attribution(row: RunRow) -> UsageAttribution:
    """Split one recorded run's time and spend. Everything it needs is already in the row."""

    usage = row.result.llm_usage
    wall = _number(row.result.latency_ms)
    run_cost = _number(row.result.cost_usd)
    tools = len(row.tool_calls)
    if not isinstance(usage, Mapping) or not usage:
        return UsageAttribution(
            case_id=row.case_id,
            variant_id=row.variant_id,
            repeat=row.repeat,
            attributable=False,
            reason="the run recorded no llm_usage, so its time and spend cannot be attributed",
            wall_clock_ms=wall,
            llm_latency_ms=None,
            llm_share=None,
            llm_calls=None,
            failed_calls=None,
            input_tokens=None,
            output_tokens=None,
            tokens_complete=None,
            llm_cost_usd=None,
            run_cost_usd=run_cost,
            llm_cost_share=None,
            tool_calls=tools,
        )

    notes: list[str] = []
    llm_latency = _number(usage.get("llm_latency_ms"))
    llm_calls = _count(usage.get("llm_call_count"))
    with_tokens = _count(usage.get("token_count_available_call_count"))
    llm_cost = _number(usage.get("estimated_cost_usd"))

    share: float | None = None
    if llm_latency is not None and wall:
        share = llm_latency / wall
        if share > 1.0:
            notes.append("llm time exceeds wall clock; calls overlapped")
    elif llm_latency is not None:
        notes.append("the run recorded no wall-clock latency, so the llm share cannot be computed")

    tokens_complete: bool | None = None
    if llm_calls is not None and with_tokens is not None:
        tokens_complete = with_tokens >= llm_calls
        if not tokens_complete:
            notes.append(f"only {with_tokens} of {llm_calls} calls reported token counts; totals are a floor")

    by_role = _by_role(usage.get("calls"))
    if not by_role:
        notes.append("the envelope carried no per-call detail, so time and spend cannot be split by role")

    cost_share = llm_cost / run_cost if llm_cost is not None and run_cost else None
    return UsageAttribution(
        case_id=row.case_id,
        variant_id=row.variant_id,
        repeat=row.repeat,
        wall_clock_ms=wall,
        run_cost_usd=run_cost,
        tool_calls=tools,
        attributable=True,
        reason=None,
        llm_latency_ms=llm_latency,
        llm_share=share,
        llm_calls=llm_calls,
        failed_calls=_count(usage.get("failed_call_count")),
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
        tokens_complete=tokens_complete,
        llm_cost_usd=llm_cost,
        llm_cost_share=cost_share,
        by_role=by_role,
        notes=tuple(notes),
    )


def _by_role(calls: Any) -> dict[str, RoleUsage]:
    """Per-role totals over the calls that reported one.

    A call with no `client_role` is pooled under "unknown" rather than dropped: its tokens were
    spent whether or not the envelope said who spent them.
    """

    if not isinstance(calls, Sequence) or isinstance(calls, (str, bytes)):
        return {}
    grouped: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for call in calls:
        if isinstance(call, Mapping):
            role = str(call.get("client_role") or "unknown")
            grouped[role].append(call)

    rolled: dict[str, RoleUsage] = {}
    for role, entries in grouped.items():
        latencies = [v for v in (_number(e.get("latency_ms")) for e in entries) if v is not None]
        inputs = [v for v in (_count(e.get("input_tokens")) for e in entries) if v is not None]
        outputs = [v for v in (_count(e.get("output_tokens")) for e in entries) if v is not None]
        costs = [v for v in (_number(e.get("estimated_cost_usd")) for e in entries) if v is not None]
        rolled[role] = RoleUsage(
            role=role,
            calls=len(entries),
            latency_ms=sum(latencies) if latencies else None,
            input_tokens=sum(inputs) if inputs else None,
            output_tokens=sum(outputs) if outputs else None,
            cost_usd=sum(costs) if costs else None,
            calls_missing_tokens=len(entries) - len(inputs),
        )
    return rolled


def usage_attributions(run: RepeatedRun, variant_id: str) -> tuple[UsageAttribution, ...]:
    """Split every row of one variant, in the run's own order."""

    return tuple(usage_attribution(row) for row in run.rows if row.variant_id == variant_id)


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """A variant's runs pooled, over the runs that said.

    `attributed_runs` is the denominator that matters: a mean over three of fifty runs is a fact
    about those three, and printing it beside `runs` is what keeps that visible.
    """

    variant_id: str
    runs: int
    attributed_runs: int
    mean_llm_share: float | None
    mean_llm_calls: float | None
    mean_tool_calls: float | None
    mean_input_tokens: float | None
    mean_llm_cost_usd: float | None
    by_role: Mapping[str, RoleUsage]
    reason: str | None = None


def usage_summary(run: RepeatedRun, variant_id: str) -> UsageSummary:
    """Pool one variant's attributions. With none attributable it says so and reports no means."""

    splits = usage_attributions(run, variant_id)
    if not splits:
        raise ValueError(f"the run has no rows for variant {variant_id!r}")
    attributed = [split for split in splits if split.attributable]
    mean_tools = sum(split.tool_calls for split in splits) / len(splits)
    if not attributed:
        return UsageSummary(
            variant_id=variant_id,
            runs=len(splits),
            attributed_runs=0,
            mean_llm_share=None,
            mean_llm_calls=None,
            mean_tool_calls=mean_tools,
            mean_input_tokens=None,
            mean_llm_cost_usd=None,
            by_role={},
            reason="no run carried an llm_usage envelope, so time and spend cannot be attributed",
        )

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    pooled: dict[str, list[RoleUsage]] = collections.defaultdict(list)
    for split in attributed:
        for role, usage in split.by_role.items():
            pooled[role].append(usage)
    by_role = {
        role: RoleUsage(
            role=role,
            calls=sum(u.calls for u in entries),
            latency_ms=sum(u.latency_ms for u in entries if u.latency_ms is not None) or None,
            input_tokens=sum(u.input_tokens for u in entries if u.input_tokens is not None) or None,
            output_tokens=sum(u.output_tokens for u in entries if u.output_tokens is not None) or None,
            cost_usd=sum(u.cost_usd for u in entries if u.cost_usd is not None) or None,
            calls_missing_tokens=sum(u.calls_missing_tokens for u in entries),
        )
        for role, entries in pooled.items()
    }
    return UsageSummary(
        variant_id=variant_id,
        runs=len(splits),
        attributed_runs=len(attributed),
        mean_llm_share=mean([s.llm_share for s in attributed if s.llm_share is not None]),
        mean_llm_calls=mean([float(s.llm_calls) for s in attributed if s.llm_calls is not None]),
        mean_tool_calls=mean_tools,
        mean_input_tokens=mean([float(s.input_tokens) for s in attributed if s.input_tokens is not None]),
        mean_llm_cost_usd=mean([s.llm_cost_usd for s in attributed if s.llm_cost_usd is not None]),
        by_role=by_role,
    )


__all__ = ["RoleUsage", "UsageAttribution", "UsageSummary", "usage_attribution", "usage_attributions", "usage_summary"]
