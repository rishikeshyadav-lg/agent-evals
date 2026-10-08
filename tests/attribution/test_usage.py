"""Where one run's time and money went, read from the llm_usage envelope."""

from __future__ import annotations

import pytest
from _attribution_builders import row, run

from agent_evals.attribution.usage import usage_attribution, usage_summary

FULL = {
    "llm_call_count": 2,
    "failed_call_count": 0,
    "token_count_available_call_count": 2,
    "llm_latency_ms": 800.0,
    "input_tokens": 103_477,
    "output_tokens": 1_144,
    "estimated_cost_usd": 0.3276,
    "calls": [
        {"client_role": "planner", "latency_ms": 500.0, "input_tokens": 51_392, "output_tokens": 240,
         "estimated_cost_usd": 0.1578},
        {"client_role": "planner", "latency_ms": 300.0, "input_tokens": 52_085, "output_tokens": 904,
         "estimated_cost_usd": 0.1698},
    ],
}


def test_a_full_envelope_splits_time_spend_and_tokens_by_role() -> None:
    split = usage_attribution(row(llm_usage=FULL, latency_ms=1_000.0, cost_usd=0.3276))

    assert split.attributable is True
    assert split.llm_share == pytest.approx(0.8)
    assert split.input_tokens == 103_477
    assert split.by_role["planner"].calls == 2
    assert split.by_role["planner"].input_tokens == 103_477


def test_an_empty_envelope_is_not_attributable_and_reports_no_zeros() -> None:
    """A 0% llm share would read as "the model is not the problem", the opposite of what is known."""

    split = usage_attribution(row(llm_usage={}, latency_ms=1_000.0))

    assert split.attributable is False
    assert split.llm_share is None
    assert split.input_tokens is None
    assert "cannot be attributed" in split.reason


def test_totals_without_per_call_detail_are_still_attributed() -> None:
    split = usage_attribution(row(llm_usage={k: v for k, v in FULL.items() if k != "calls"}, latency_ms=1_000.0))

    assert split.input_tokens == 103_477
    assert split.by_role == {}
    assert any("by role" in note for note in split.notes)


def test_a_call_with_no_role_is_pooled_rather_than_dropped() -> None:
    """Its tokens were spent whether or not the envelope said who spent them."""

    usage = dict(FULL, calls=[{"input_tokens": 10, "latency_ms": 5.0}])

    split = usage_attribution(row(llm_usage=usage, latency_ms=1_000.0))

    assert split.by_role["unknown"].input_tokens == 10


def test_missing_token_counts_mark_the_total_a_floor() -> None:
    usage = dict(FULL, token_count_available_call_count=1)

    split = usage_attribution(row(llm_usage=usage, latency_ms=1_000.0))

    assert split.tokens_complete is False
    assert any("floor" in note for note in split.notes)


def test_llm_time_above_wall_clock_is_reported_not_clamped() -> None:
    """Concurrent calls really do sum past the wall clock, and a clamped 1.0 is a fact destroyed."""

    split = usage_attribution(row(llm_usage=dict(FULL, llm_latency_ms=2_000.0), latency_ms=1_000.0))

    assert split.llm_share == pytest.approx(2.0)
    assert any("overlapped" in note for note in split.notes)


def test_a_missing_wall_clock_leaves_the_share_unknown_but_keeps_the_llm_time() -> None:
    split = usage_attribution(row(llm_usage=FULL, latency_ms=None))

    assert split.llm_latency_ms == pytest.approx(800.0)
    assert split.llm_share is None


def test_numbers_that_are_strings_or_negative_are_not_usage() -> None:
    usage = {"input_tokens": "lots", "llm_latency_ms": -5.0, "estimated_cost_usd": 0.1}

    split = usage_attribution(row(llm_usage=usage, latency_ms=1_000.0))

    assert split.input_tokens is None
    assert split.llm_latency_ms is None
    assert split.llm_cost_usd == pytest.approx(0.1)


def test_a_summary_over_runs_that_said_nothing_reports_no_means() -> None:
    summary = usage_summary(run(row(llm_usage={}), row(llm_usage={})), "prd")

    assert summary.attributed_runs == 0
    assert summary.mean_input_tokens is None
    assert "cannot be attributed" in summary.reason


def test_a_summary_names_the_denominator_that_matters() -> None:
    """A mean over two of three runs is a fact about those two."""

    summary = usage_summary(run(row(llm_usage=FULL, latency_ms=1_000.0), row(llm_usage={})), "prd")

    assert (summary.runs, summary.attributed_runs) == (2, 1)
    assert summary.mean_input_tokens == pytest.approx(103_477)


def test_a_variant_with_no_rows_raises() -> None:
    with pytest.raises(ValueError, match="no rows for variant"):
        usage_summary(run(row()), "rc1")
