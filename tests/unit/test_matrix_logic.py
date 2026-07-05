from datetime import datetime

import pytest

from app.matrix_logic import (apply_disruption, calculate_gaps,
                              merge_activities, parse_date)


@pytest.fixture
def sample_profile():
    return {
        "children": [{"name": "Emily"}, {"name": "Jack"}],
        "baseline_coverage": [
            {
                "name": "School",
                "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                "start_time": "08:30",
                "end_time": "15:00",
                "months": ["July"]  # For testing purposes, we'll set it to July
            }
        ]
    }

def test_merge_activities():
    matrix = {"activities": [], "gaps": []}
    new_acts = [
        {
            "child_name": "Emily",
            "activity_title": "Soccer Camp",
            "start_date": "2026-07-06",
            "end_date": "2026-07-10",
            "start_time": "09:00",
            "end_time": "12:00"
        }
    ]
    
    updated = merge_activities(matrix, new_acts)
    assert len(updated["activities"]) == 1
    assert updated["activities"][0]["child_name"] == "Emily"
    assert updated["activities"][0]["status"] == "ACTIVE"
    assert "id" in updated["activities"][0]

def test_apply_disruption():
    matrix = {
        "activities": [
            {
                "id": "act_1",
                "child_name": "Emily",
                "activity_title": "Soccer Camp",
                "start_date": "2026-07-06",
                "end_date": "2026-07-10",
                "start_time": "09:00",
                "end_time": "12:00",
                "status": "ACTIVE"
            }
        ]
    }
    
    disruption = {
        "child_name": "Emily",
        "date": "2026-07-07",
        "start_time": "09:30",
        "end_time": "10:30",
        "description": "Nanny called out sick",
        "disruption_type": "SICK_LEAVE"
    }
    
    updated = apply_disruption(matrix, disruption)
    assert updated["activities"][0]["status"] == "DISRUPTED"
    assert "[DISRUPTED:" in updated["activities"][0]["notes"]


def _camp_matrix():
    return {
        "activities": [
            {
                "id": "act_1",
                "child_name": "Emily",
                "activity_title": "Wilderness Explorers Camp",
                "start_date": "2026-08-03",
                "end_date": "2026-08-07",
                "start_time": "09:00",
                "end_time": "15:30",
                "status": "ACTIVE",
            }
        ]
    }


def test_apply_disruption_matches_by_activity_title_without_child():
    # e.g. "Wilderness Explorers Camp is cancelled on August 5th" names no child.
    disruption = {
        "child_name": "",
        "activity_title": "Wilderness Explorers Camp",
        "date": "2026-08-05",
        "description": "Camp cancelled due to weather",
        "disruption_type": "CANCELLATION",
    }

    updated = apply_disruption(_camp_matrix(), disruption)
    assert updated["activities"][0]["status"] == "DISRUPTED"


def test_apply_disruption_title_match_is_case_insensitive_substring():
    disruption = {
        "child_name": "",
        "activity_title": "wilderness explorers",
        "date": "2026-08-05",
        "description": "Camp cancelled",
        "disruption_type": "CANCELLATION",
    }

    updated = apply_disruption(_camp_matrix(), disruption)
    assert updated["activities"][0]["status"] == "DISRUPTED"


def test_apply_disruption_treats_na_child_as_unspecified():
    disruption = {
        "child_name": "N/A",
        "activity_title": "Wilderness Explorers Camp",
        "date": "2026-08-05",
        "description": "Camp cancelled",
        "disruption_type": "CANCELLATION",
    }

    updated = apply_disruption(_camp_matrix(), disruption)
    assert updated["activities"][0]["status"] == "DISRUPTED"


def test_apply_disruption_without_child_or_title_changes_nothing():
    disruption = {
        "child_name": "",
        "activity_title": "",
        "date": "2026-08-05",
        "description": "Something happened",
        "disruption_type": "CANCELLATION",
    }

    updated = apply_disruption(_camp_matrix(), disruption)
    assert updated["activities"][0]["status"] == "ACTIVE"


def test_apply_disruption_wrong_title_changes_nothing():
    disruption = {
        "child_name": "",
        "activity_title": "Robotics Lab",
        "date": "2026-08-05",
        "description": "Robotics cancelled",
        "disruption_type": "CANCELLATION",
    }

    updated = apply_disruption(_camp_matrix(), disruption)
    assert updated["activities"][0]["status"] == "ACTIVE"

def test_calculate_gaps_absolute(sample_profile):
    # Test absolute gaps (Mon-Fri 9:00 to 17:00 / 540 to 1020)
    # Emily has school from 8:30 to 15:00. Care window is 9:00 to 17:00.
    # Therefore, she is covered from 9:00 to 15:00 by school.
    # She has an absolute gap from 15:00 to 17:00.
    
    activities = []
    start_date = parse_date("2026-07-06")  # Monday
    end_date = parse_date("2026-07-06")
    
    gaps = calculate_gaps(activities, sample_profile, start_date, end_date)
    
    # We expect one absolute gap for Emily from 15:00 to 17:00
    emily_gaps = [g for g in gaps if g["child_name"] == "Emily" and g["type"] == "ABSOLUTE"]
    assert len(emily_gaps) == 1
    assert emily_gaps[0]["start_time"] == "15:00"
    assert emily_gaps[0]["end_time"] == "17:00"

def test_calculate_gaps_relative(sample_profile):
    # Test relative gaps (sibling mismatch)
    # Emily has a camp from 9:00 to 12:00.
    # Jack has only school (covered 9:00 to 15:00, gap 15:00 to 17:00).
    # Since Emily has a camp from 9:00 to 12:00, and Jack is covered by school, they are both covered.
    # But what if Jack has no school and no camp?
    # Let's say Jack has an absolute gap from 9:00 to 12:00, while Emily is at camp.
    # This should trigger a relative gap for Jack: Emily has camp, Jack has no care.
    
    profile_no_school = {
        "children": [{"name": "Emily"}, {"name": "Jack"}],
        "baseline_coverage": [] # No school
    }
    
    activities = [
        {
            "child_name": "Emily",
            "activity_title": "Soccer Camp",
            "start_date": "2026-07-06",
            "end_date": "2026-07-06",
            "start_time": "09:00",
            "end_time": "12:00",
            "status": "ACTIVE"
        }
    ]
    
    start_date = parse_date("2026-07-06")
    end_date = parse_date("2026-07-06")
    
    gaps = calculate_gaps(activities, profile_no_school, start_date, end_date)
    
    # Jack has an absolute gap from 9:00 to 17:00.
    # He should also have a relative gap from 9:00 to 12:00 because Emily is at camp.
    jack_rel_gaps = [g for g in gaps if g["child_name"] == "Jack" and g["type"] == "RELATIVE"]
    assert len(jack_rel_gaps) == 1
    assert jack_rel_gaps[0]["start_time"] == "09:00"
    assert jack_rel_gaps[0]["end_time"] == "12:00"

def test_calculate_gaps_honors_frontend_default_baseline_schema():
    profile = {
        "children": [{"name": "Emily"}],
        "baseline_coverage": [
            {
                "name": "School",
                "days": [1, 2, 3, 4, 5],
                "start_time": "08:30",
                "end_time": "15:00",
                "start_date": "2026-09-01",
                "end_date": "2027-06-30",
            }
        ],
    }

    gaps = calculate_gaps(
        [],
        profile,
        parse_date("2026-09-01"),  # Tuesday, first school day in default profile
        parse_date("2026-09-01"),
    )

    emily_gaps = [g for g in gaps if g["child_name"] == "Emily" and g["type"] == "ABSOLUTE"]
    assert len(emily_gaps) == 1
    assert emily_gaps[0]["start_time"] == "15:00"
    assert emily_gaps[0]["end_time"] == "17:00"


def test_calculate_gaps_respects_frontend_baseline_date_range():
    profile = {
        "children": [{"name": "Emily"}],
        "baseline_coverage": [
            {
                "name": "School",
                "days": [1, 2, 3, 4, 5],
                "start_time": "08:30",
                "end_time": "15:00",
                "start_date": "2026-09-01",
                "end_date": "2027-06-30",
            }
        ],
    }

    gaps = calculate_gaps(
        [],
        profile,
        parse_date("2026-08-31"),  # Monday before the default school year starts
        parse_date("2026-08-31"),
    )

    emily_gaps = [g for g in gaps if g["child_name"] == "Emily" and g["type"] == "ABSOLUTE"]
    assert len(emily_gaps) == 1
    assert emily_gaps[0]["start_time"] == "09:00"
    assert emily_gaps[0]["end_time"] == "17:00"


def test_calculate_gaps_accepts_matrix_grid_days_of_week_alias():
    profile = {
        "children": [{"name": "Emily"}],
        "baseline_coverage": [
            {
                "name": "School",
                "days_of_week": [1, 2, 3, 4, 5],
                "start_time": "08:30",
                "end_time": "15:00",
                "start_date": "2026-09-01",
                "end_date": "2027-06-30",
            }
        ],
    }

    gaps = calculate_gaps([], profile, parse_date("2026-09-02"), parse_date("2026-09-02"))

    emily_gaps = [g for g in gaps if g["child_name"] == "Emily" and g["type"] == "ABSOLUTE"]
    assert len(emily_gaps) == 1
    assert emily_gaps[0]["start_time"] == "15:00"
    assert emily_gaps[0]["end_time"] == "17:00"
