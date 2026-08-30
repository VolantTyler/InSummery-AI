"""Tests for the deterministic HITL escalation signals.

The property under test throughout: these checks fire on the *extraction*,
never on the model's opinion of itself. Several tests assert escalation on
input the model would have rated confidence 100.
"""
import datetime

import pytest

from app.extraction_risk import (
    MAX_PLAUSIBLE_MONTHS_AHEAD,
    assess_extraction,
    describe_for_human,
)

TODAY = datetime.date(2026, 8, 28)
CHILDREN = [{"name": "Sam"}, {"name": "Pat"}, {"name": "Alex"}]


def activity(**overrides):
    base = {
        "child_name": "Sam",
        "activity_title": "Robotics Camp",
        "start_date": "2026-09-07",
        "end_date": "2026-09-11",
        "start_time": "09:00",
        "end_time": "15:00",
        "location": "Museum",
        "notes": "Bring lunch",
    }
    base.update(overrides)
    return base


def assess(acts, **kw):
    kw.setdefault("profile_children", CHILDREN)
    kw.setdefault("today", TODAY)
    return assess_extraction(acts, **kw)


# --- the case that motivated this module ------------------------------------

def test_unresolved_child_name_escalates():
    """The measured failure: activity attached to a name no child matches,
    reported by the model at confidence 100.

    "Priya" (not "Sammy") is the unresolved example here: resolve_child_name
    now understands "Sammy" as a nickname of the profile's "Sam" (see
    app/name_aliases.py), so a name genuinely absent from the profile is
    needed to exercise this escalation path.
    """
    result = assess([activity(child_name="Priya")])
    assert result["escalate"] is True
    assert "unresolved_child_name" in result["codes"]
    assert "Priya" in result["reasons"][0]["detail"]
    assert "Sam" in result["reasons"][0]["detail"]  # names the known children


def test_known_child_does_not_escalate():
    assert assess([activity(child_name="Sam")])["escalate"] is False


def test_fuller_name_form_does_not_escalate():
    """resolve_child_name maps 'Sam Smith' to 'Sam'; that is correct, not a risk."""
    assert assess([activity(child_name="Sam Smith")])["escalate"] is False


def test_nickname_form_does_not_escalate():
    """resolve_child_name maps 'Sammy' to 'Sam'; that is correct, not a risk."""
    assert assess([activity(child_name="Sammy")])["escalate"] is False


# --- structural completeness ------------------------------------------------

@pytest.mark.parametrize(
    "field", ["child_name", "activity_title", "start_date", "end_date", "start_time", "end_time"]
)
def test_every_required_field_escalates_when_missing(field):
    result = assess([activity(**{field: ""})])
    assert result["escalate"] is True
    assert "missing_required_field" in result["codes"]


def test_no_activities_escalates():
    result = assess([])
    assert result["escalate"] is True
    assert "no_activities" in result["codes"]


# --- data corruption --------------------------------------------------------

@pytest.mark.parametrize("value", ["[CHILD_A]", "CHILD_B", "Camp for [CHILD_A]"])
def test_placeholder_leak_escalates(value):
    """An unresolved placeholder means mask/unmask failed and the token is
    about to be written into the family's saved schedule."""
    result = assess([activity(activity_title=value)])
    assert result["escalate"] is True
    assert "placeholder_leak" in result["codes"]


def test_ordinary_bracketed_text_is_not_a_placeholder():
    assert assess([activity(notes="Session [morning] group")])["escalate"] is False


# --- date plausibility ------------------------------------------------------

def test_inverted_range_escalates():
    result = assess([activity(start_date="2026-09-11", end_date="2026-09-07")])
    assert "inverted_date_range" in result["codes"]


def test_range_entirely_in_the_past_does_not_escalate():
    """Deliberately not a signal.

    Escalating on "already ended" was tried and removed: it fires on any
    legitimately old email (importing a past season, re-processing an archive)
    while the consequence is mild, since a past-dated activity just sits in
    history. A year-inference error that lands in the future is caught by
    date_range_implausibly_far instead. See the module docstring.
    """
    result = assess([activity(start_date="2026-06-01", end_date="2026-06-05")])
    assert result["escalate"] is False


def test_implausibly_distant_range_escalates():
    far = TODAY + datetime.timedelta(days=MAX_PLAUSIBLE_MONTHS_AHEAD * 30 + 40)
    result = assess([activity(start_date=far.isoformat(),
                              end_date=(far + datetime.timedelta(days=4)).isoformat())])
    assert "date_range_implausibly_far" in result["codes"]


def test_normal_future_range_does_not_escalate():
    soon = TODAY + datetime.timedelta(days=60)
    assert assess([activity(start_date=soon.isoformat(),
                            end_date=(soon + datetime.timedelta(days=4)).isoformat())
                   ])["escalate"] is False


# --- guardrail integration --------------------------------------------------

def test_failed_guardrail_escalates():
    """The guardrail result was computed and traced but nothing acted on it."""
    result = assess([activity()], guardrail={"passed": False, "violations": ["possible_email_leak"]})
    assert result["escalate"] is True
    assert "guardrail_failed" in result["codes"]
    assert "possible_email_leak" in result["reasons"][0]["detail"]


def test_passing_guardrail_does_not_escalate():
    assert assess([activity()], guardrail={"passed": True, "violations": []})["escalate"] is False


# --- multi-activity ---------------------------------------------------------

def test_one_bad_activity_among_good_ones_escalates_and_is_located():
    result = assess([activity(), activity(child_name="Priya"), activity()])
    assert result["escalate"] is True
    bad = [r for r in result["reasons"] if r["code"] == "unresolved_child_name"]
    assert len(bad) == 1 and bad[0]["activity_index"] == 1


# --- the human-facing message ----------------------------------------------

def test_message_names_the_problem_not_a_percentage():
    msg = describe_for_human(assess([activity(child_name="Priya")]))
    assert "Priya" in msg
    assert "%" not in msg
    assert "confidence" not in msg.lower()


def test_message_is_neutral_when_nothing_fired():
    assert "confirm" in describe_for_human({"reasons": []}).lower()


# --- independence from self-reported confidence ------------------------------

def test_assessment_ignores_confidence_score_entirely():
    """The whole point: a model claiming 100 cannot suppress these signals."""
    payload = [dict(activity(child_name="Priya"), confidence_score=100)]
    assert assess(payload)["escalate"] is True


def test_no_profile_children_does_not_crash_or_escalate_on_names():
    result = assess_extraction([activity()], profile_children=[], today=TODAY)
    assert "unresolved_child_name" not in result["codes"]
