from app.evaluation.scoring import (
    exact_score,
    fuzzy_score,
    score_triager_case,
    score_registration_activity,
    score_disruption,
    pick_best_activity,
    aggregate,
    REGISTRATION_FIELD_WEIGHTS,
    DISRUPTION_FIELD_WEIGHTS,
)


def test_field_weights_sum_to_one():
    assert abs(sum(REGISTRATION_FIELD_WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(DISRUPTION_FIELD_WEIGHTS.values()) - 1.0) < 1e-9


def test_exact_score_normalizes_case_and_whitespace():
    assert exact_score("Emily", "  emily ") == 1.0
    assert exact_score("Emily", "Emma") == 0.0
    assert exact_score(None, "") == 1.0


def test_fuzzy_score_containment_and_similarity():
    assert fuzzy_score("Junior Striker Soccer Camp", "Junior Striker Soccer Camp (Ages 9-11)") == 1.0
    assert fuzzy_score("Soccer Camp", "soccer camp") == 1.0
    assert fuzzy_score("Soccer Camp", "Chess Tournament") < 0.5
    assert fuzzy_score(None, None) == 1.0
    assert fuzzy_score("something", None) == 0.0


def test_score_triager_case():
    assert score_triager_case("registration", "registration") == 1.0
    assert score_triager_case("registration", "disruption") == 0.0


EXPECTED_ACTIVITY = {
    "child_name": "Emily",
    "activity_title": "Junior Striker Soccer Camp (Ages 9-11)",
    "start_date": "2026-07-06",
    "end_date": "2026-07-10",
    "start_time": "09:00",
    "end_time": "12:00",
    "location": "Green Valley Sports Complex, Pitch 3, 789 Athletic Way, Springville",
    "notes": "Coach: Dave Miller. Wear shin guards.",
}


def test_perfect_registration_extraction_scores_one():
    result = score_registration_activity(EXPECTED_ACTIVITY, dict(EXPECTED_ACTIVITY))
    assert result["score"] == 1.0
    assert all(v == 1.0 for v in result["field_scores"].values())


def test_wrong_child_and_dates_lose_their_weights():
    predicted = dict(EXPECTED_ACTIVITY)
    predicted["child_name"] = "Jack"
    predicted["start_date"] = "2026-07-07"
    result = score_registration_activity(EXPECTED_ACTIVITY, predicted)
    assert result["field_scores"]["child_name"] == 0.0
    assert result["field_scores"]["start_date"] == 0.0
    assert abs(result["score"] - (1.0 - 0.25 - 0.15)) < 1e-6


def test_fuzzy_title_below_threshold_scores_zero():
    predicted = dict(EXPECTED_ACTIVITY)
    predicted["activity_title"] = "Advanced Robotics Workshop"
    result = score_registration_activity(EXPECTED_ACTIVITY, predicted)
    assert result["field_scores"]["activity_title"] == 0.0


def test_pick_best_activity_selects_matching_child():
    other = dict(EXPECTED_ACTIVITY)
    other["child_name"] = "Jack"
    other["activity_title"] = "Robotics Camp"
    best = pick_best_activity(EXPECTED_ACTIVITY, [other, dict(EXPECTED_ACTIVITY)])
    assert best["child_name"] == "Emily"
    assert pick_best_activity(EXPECTED_ACTIVITY, []) is None


def test_score_disruption():
    expected = {
        "child_name": "Emma",
        "date": "2026-07-07",
        "disruption_type": "SICK_LEAVE",
        "description": "Nanny Jessica is sick and cannot watch Emma",
    }
    perfect = score_disruption(expected, dict(expected))
    assert perfect["score"] == 1.0

    wrong_type = dict(expected)
    wrong_type["disruption_type"] = "CANCELLATION"
    result = score_disruption(expected, wrong_type)
    assert result["field_scores"]["disruption_type"] == 0.0
    assert abs(result["score"] - 0.80) < 1e-6


def test_aggregate():
    assert aggregate([]) == 0.0
    assert aggregate([1.0, 0.0]) == 0.5
