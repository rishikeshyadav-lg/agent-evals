"""A scorer that reports several metrics can now explain each one.

A plain mapping says only what the numbers were. A scorer checking figures against a table needs to
say which field disagreed and by how much, or its report cannot be acted on.
"""

from __future__ import annotations

import pytest

from agent_evals import MultiScoreResult, ScoreResult, normalize_scores


def test_several_metrics_each_keep_their_own_detail() -> None:
    result = MultiScoreResult(
        {"spend_match": 1.0, "clicks_match": 0.0},
        {"clicks_match": {"expected": 400.0, "claimed": 380.0}},
    )

    metrics, details = normalize_scores(result, scorer=None)

    assert metrics == {"spend_match": 1.0, "clicks_match": 0.0}
    assert details == {"clicks_match": {"expected": 400.0, "claimed": 380.0}}


def test_a_metric_needs_no_detail() -> None:
    """Only the interesting metric has to explain itself."""

    metrics, details = normalize_scores(MultiScoreResult({"a": 1.0, "b": 1.0}), scorer=None)

    assert metrics == {"a": 1.0, "b": 1.0}
    assert details == {}


def test_detail_for_a_metric_nobody_scored_is_refused() -> None:
    """The error path: such a detail would be dropped on the way to the report, so say so loudly."""

    with pytest.raises(ValueError, match="did not score"):
        MultiScoreResult({"a": 1.0}, {"typo": {"why": "nothing scores this"}})


def test_a_score_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        MultiScoreResult({"a": float("inf")})


def test_the_older_return_shapes_are_untouched() -> None:
    """A plain mapping still carries no detail, and a single ScoreResult still reports under its name."""

    assert normalize_scores({"x": 1.0}, scorer=None) == ({"x": 1.0}, {})
    assert normalize_scores(ScoreResult(1.0, feedback="why"), scorer="s") == ({"s": 1.0}, {"s": {"feedback": "why"}})


def test_an_unknown_return_type_names_what_is_allowed() -> None:
    with pytest.raises(ValueError, match="MultiScoreResult"):
        normalize_scores(object(), scorer="s")  # type: ignore[arg-type]
