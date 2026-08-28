"""Tests for set-based activity scoring.

The point of these functions is to make two failures visible that
`pick_best_activity` structurally cannot see: a MISSED activity and an
INVENTED one. Several tests below assert the contrast directly.
"""
import pytest

from app.evaluation.scoring import (
    ACTIVITY_MATCH_THRESHOLD,
    match_activities,
    pick_best_activity,
    score_activity_set,
    score_registration_activity,
)


def activity(child, title, start="2026-07-06", end="2026-07-10",
             t0="09:00", t1="12:00", location="Field 1", notes="Bring water"):
    return {
        "child_name": child, "activity_title": title,
        "start_date": start, "end_date": end,
        "start_time": t0, "end_time": t1,
        "location": location, "notes": notes,
    }


SOCCER = activity("Pat", "Junior Striker Soccer Camp")
ROBOTICS = activity("Sam", "Astro Robotics Camp", start="2026-07-13",
                    end="2026-07-17", t1="15:00", location="Museum")
JUNK = activity("Alex", "Newsletter Advertisement", start="2026-01-01",
                end="2026-01-01", t0="00:00", t1="00:00", location="", notes="")


def test_perfect_extraction_scores_one():
    assert score_activity_set([SOCCER, ROBOTICS], [SOCCER, ROBOTICS])["score"] == 1.0


def test_order_does_not_matter():
    assert score_activity_set([SOCCER, ROBOTICS], [ROBOTICS, SOCCER])["score"] == 1.0


def test_missed_activity_costs_score_where_old_scorer_was_blind():
    """Two siblings registered, one extracted."""
    old = score_registration_activity(SOCCER, pick_best_activity(SOCCER, [SOCCER]))["score"]
    assert old == 1.0, "baseline: the single-activity scorer sees nothing wrong"

    new = score_activity_set([SOCCER, ROBOTICS], [SOCCER])
    assert new["activity_recall"] == 0.5
    assert new["activity_precision"] == 1.0
    assert new["score"] < 1.0
    assert new["missed_expected"] == [1]


def test_hallucinated_activity_costs_score():
    """One real booking, two invented ones alongside it."""
    result = score_activity_set([SOCCER], [SOCCER, JUNK, JUNK])
    assert result["activity_recall"] == 1.0
    assert result["activity_precision"] == pytest.approx(1 / 3, abs=1e-4)
    assert result["score"] < 1.0
    assert len(result["spurious_predicted"]) == 2


def test_assignment_is_one_to_one():
    """One prediction cannot satisfy two expected activities."""
    result = match_activities([SOCCER, SOCCER], [SOCCER])
    assert len(result["pairs"]) == 1
    assert result["missed_expected"] == [1]


def test_below_threshold_pair_counts_as_miss_plus_spurious():
    """A badly wrong prediction must not paper over a missing activity."""
    result = match_activities([SOCCER], [JUNK])
    assert result["pairs"] == []
    assert result["missed_expected"] == [0]
    assert result["spurious_predicted"] == [0]
    assert result["activity_f1"] == 0.0


def test_empty_prediction_scores_zero():
    result = score_activity_set([SOCCER], [])
    assert result["score"] == 0.0
    assert result["activity_recall"] == 0.0


def test_both_empty_is_a_pass():
    result = score_activity_set([], [])
    assert result["activity_precision"] == 1.0
    assert result["activity_recall"] == 1.0


def test_matched_field_score_separates_coverage_from_accuracy():
    """f1 and field quality answer different questions.

    Finding every activity but filling them in sloppily is a different bug
    from finding half of them perfectly, and the report must tell them apart.
    """
    sloppy = dict(SOCCER, start_time="10:00", end_time="13:00")  # wrong times
    result = score_activity_set([SOCCER, ROBOTICS], [sloppy, ROBOTICS])
    assert result["activity_f1"] == 1.0            # both activities found
    assert result["matched_field_score"] < 1.0     # but one is wrong
    assert result["score"] < 1.0


def test_threshold_is_documented_and_sane():
    assert 0.0 < ACTIVITY_MATCH_THRESHOLD < 1.0


def test_determinism_across_repeated_runs():
    args = ([SOCCER, ROBOTICS], [ROBOTICS, JUNK, SOCCER])
    first = score_activity_set(*args)
    for _ in range(5):
        assert score_activity_set(*args) == first
