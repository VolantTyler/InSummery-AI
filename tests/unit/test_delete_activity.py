import copy
import pytest

from app.matrix_logic import delete_activity


def _make_matrix(**overrides):
    act = {
        "id": "act_1",
        "child_name": "Emily",
        "activity_title": "Soccer Camp",
        "start_date": "2026-07-06",
        "end_date": "2026-07-10",
        "start_time": "09:00",
        "end_time": "12:00",
        "status": "ACTIVE",
    }
    act.update(overrides)
    return {"activities": [act], "gaps": []}


def test_delete_activity_series():
    matrix = _make_matrix(google_event_id="g_123")
    result = delete_activity(matrix, "act_1", "series")

    assert len(result["activities"]) == 0
    assert "g_123" in result["deleted_google_event_ids"]


def test_delete_activity_single_edge_start():
    matrix = _make_matrix()
    result = delete_activity(matrix, "act_1", "single", "2026-07-06")

    assert len(result["activities"]) == 1
    assert result["activities"][0]["start_date"] == "2026-07-07"
    assert result["activities"][0]["end_date"] == "2026-07-10"


def test_delete_activity_single_edge_end():
    matrix = _make_matrix()
    result = delete_activity(matrix, "act_1", "single", "2026-07-10")

    assert len(result["activities"]) == 1
    assert result["activities"][0]["start_date"] == "2026-07-06"
    assert result["activities"][0]["end_date"] == "2026-07-09"


def test_delete_activity_single_split():
    matrix = _make_matrix(google_event_id="g_123")
    result = delete_activity(matrix, "act_1", "single", "2026-07-08")

    activities = result["activities"]
    assert len(activities) == 2

    # Part 1 keeps the original ID and google_event_id
    assert activities[0]["id"] == "act_1"
    assert activities[0]["start_date"] == "2026-07-06"
    assert activities[0]["end_date"] == "2026-07-07"
    assert activities[0]["google_event_id"] == "g_123"

    # Part 2 gets a new ID and no google_event_id
    assert activities[1]["id"] != "act_1"
    assert activities[1]["start_date"] == "2026-07-09"
    assert activities[1]["end_date"] == "2026-07-10"
    assert "google_event_id" not in activities[1]


def test_delete_activity_not_found():
    matrix = _make_matrix()
    with pytest.raises(ValueError, match="not found"):
        delete_activity(matrix, "nonexistent", "series")


def test_delete_activity_single_day():
    """A single-day activity deleted as 'single' should remove it entirely."""
    matrix = _make_matrix(start_date="2026-07-08", end_date="2026-07-08", google_event_id="g_456")
    result = delete_activity(matrix, "act_1", "single", "2026-07-08")

    assert len(result["activities"]) == 0
    assert "g_456" in result["deleted_google_event_ids"]
