"""Per-segment scorecards, by slicing the run rather than reimplementing the scorecard."""

from __future__ import annotations

from _attribution_builders import row, run

from agent_evals.reporting.segments import (
    segment_run,
    segment_sizes,
    segmented_scorecards,
    unlabelled_rows,
)

METRICS = {"success": 1.0}


def test_slicing_by_category_keeps_the_settings_and_the_row_order() -> None:
    sliced = segment_run(
        run(
            row(case_id="a", category="overall_summary"),
            row(case_id="b", category="ranking"),
            row(case_id="c", category="overall_summary"),
        )
    )

    assert list(sliced) == ["overall_summary", "ranking"]
    assert [r.case_id for r in sliced["overall_summary"].rows] == ["a", "c"]
    assert sliced["overall_summary"].settings.repeats == 1


def test_every_repeat_of_a_case_lands_in_the_same_segment() -> None:
    """What keeps the case-clustered bootstrap valid inside a segment: it resamples whole cases."""

    sliced = segment_run(
        run(
            row(case_id="a", repeat=0, category="ranking"),
            row(case_id="a", repeat=1, category="ranking"),
        )
    )

    assert len(sliced) == 1
    assert len(sliced["ranking"].rows) == 2


def test_rows_the_label_left_out_are_reported_not_dropped() -> None:
    left_out = unlabelled_rows(run(row(case_id="a", category=None), row(case_id="b", category="ranking")))

    assert [r.case_id for r in left_out] == ["a"]


def test_a_segment_scorecard_has_the_same_entries_as_the_whole_run() -> None:
    """A segmented scorecard must be the same scorecard or segments cannot be compared."""

    rows = [row(case_id=f"c{i}", category="overall_summary", metrics=METRICS) for i in range(4)]
    whole = run(*rows)

    segments = segmented_scorecards(whole, "prd")
    from agent_evals.reporting.report import build_scorecard

    assert set(segments["overall_summary"].scorecard.entries) == set(build_scorecard(whole, "prd").entries)


def test_a_segment_under_the_minimum_gets_no_scorecard_and_says_why() -> None:
    """An interval over two cases carries no information, and printing one beside a real interval is
    how a segment nobody has evidence about gets acted on."""

    segments = segmented_scorecards(
        run(
            row(case_id="a", category="ranking", metrics=METRICS),
            row(case_id="b", category="ranking", metrics=METRICS),
        ),
        "prd",
    )

    assert segments["ranking"].scorecard is None
    assert "carries no information" in segments["ranking"].reason


def test_a_segment_that_cannot_be_scored_is_reported_rather_than_taking_the_report_down() -> None:
    rows = [row(case_id=f"c{i}", category="ranking", metrics={}) for i in range(4)]

    segments = segmented_scorecards(run(*rows), "prd")

    assert segments["ranking"].scorecard is None
    assert segments["ranking"].reason


def test_segment_sizes_say_whether_a_segmentation_is_worth_reading() -> None:
    sizes = segment_sizes(run(row(case_id="a", category="ranking"), row(case_id="b", category="ranking")))

    assert sizes == {"ranking": 2}


def test_segmenting_a_mined_dataset_by_pattern_is_empty_until_the_caller_fills_it() -> None:
    """build_dataset writes category and neither pattern_key nor set."""

    from agent_evals.reporting.segments import by_pattern_key

    assert segment_run(run(row(case_id="a", category="ranking")), by_pattern_key) == {}
