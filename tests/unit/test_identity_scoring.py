"""Unit tests for the offline identity scorers.

These test the *instrument*, not the masker: they use a stub masker with known
behavior so a scorer bug cannot hide behind a masker bug (and vice versa).
"""
import re

import pytest

from app.evaluation.identity_scoring import (
    aggregate_mask_results,
    aggregate_name_resolution,
    find_glued_placeholders,
    group_failures,
    score_mask_case,
    score_name_resolution_case,
)


class StubMasker:
    """Masker with a fixed, declared substitution table.

    Case-insensitive on purpose: PIIMasker matches case-insensitively, and a
    case-sensitive stub would quietly skip the very collisions these scorers
    exist to catch ("Sam" inside "same").
    """

    def __init__(self, table):
        self.table = table

    def mask(self, text):
        for original, placeholder in self.table.items():
            text = re.sub(re.escape(original), placeholder, text, flags=re.IGNORECASE)
        return text

    def unmask(self, text):
        for original, placeholder in self.table.items():
            text = text.replace(placeholder, original)
        return text


# --- placeholder token integrity -------------------------------------------

@pytest.mark.parametrize(
    "masked,expect_glued",
    [
        ("at the [CHILD_B]e time", True),          # masked inside "same"
        ("partici[CHILD_A]ion required", True),    # masked inside "participation"
        ("[CHILD_C]andra Reyes", True),            # masked inside "Alexandra"
        ("[CHILD_B] Smith is enrolled", False),    # whole-word mask
        ("[CHILD_B]'s camp", False),               # apostrophe is not a word char
        ("Contact [CHILD_A], [CHILD_B].", False),  # punctuation neighbours
        ("([CHILD_A])", False),
        ("no placeholders here", False),
    ],
)
def test_find_glued_placeholders(masked, expect_glued):
    assert bool(find_glued_placeholders(masked)) is expect_glued


# --- mask case scoring -----------------------------------------------------

def test_leak_is_detected_when_pii_survives():
    masker = StubMasker({"Sam": "[CHILD_A]"})
    result = score_mask_case(
        masker,
        {"id": "t", "text": "Sam Smith attends.", "must_mask": ["Sam", "Smith"]},
    )
    assert result["leaks"] == ["Smith"]
    assert result["recall"] == 0.5
    assert result["passed"] is False


def test_over_mask_is_detected_when_ordinary_word_is_mangled():
    masker = StubMasker({"Sam": "[CHILD_A]"})
    result = score_mask_case(
        masker,
        {"id": "t", "text": "at the same time", "must_not_mask": ["same"]},
    )
    assert result["over_masked"] == ["same"]
    assert result["precision"] == 0.0
    assert result["glued_placeholders"]  # the structural invariant also fires


def test_partial_over_mask_counts_by_occurrence_not_presence():
    """A span appearing twice must survive twice.

    Presence-only checking would pass a text where one of two copies was
    mangled, which is exactly how a subtle masking bug hides.
    """
    masker = StubMasker({"XX": "[P]"})
    result = score_mask_case(
        masker,
        {"id": "t", "text": "keep keep XXkeep", "must_not_mask": ["keep"]},
    )
    assert result["over_masked"] == []       # all three "keep" survive
    masker2 = StubMasker({"ke": "[P]"})
    result2 = score_mask_case(
        masker2,
        {"id": "t", "text": "keep keep", "must_not_mask": ["keep"]},
    )
    assert result2["over_masked"] == ["keep"]


def test_clean_case_passes_all_dimensions():
    masker = StubMasker({"Sam": "[CHILD_A]"})
    result = score_mask_case(
        masker,
        {
            "id": "t",
            "text": "Sam attends the morning camp.",
            "must_mask": ["Sam"],
            "must_not_mask": ["camp", "morning"],
        },
    )
    assert result["passed"] is True
    assert result["recall"] == 1.0
    assert result["precision"] == 1.0
    assert result["roundtrip_ok"] is True


def test_roundtrip_failure_is_reported():
    class LossyMasker(StubMasker):
        def unmask(self, text):
            return text  # never restores

    result = score_mask_case(
        LossyMasker({"Sam": "[CHILD_A]"}), {"id": "t", "text": "Sam attends."}
    )
    assert result["roundtrip_ok"] is False
    assert result["passed"] is False


# --- aggregation -----------------------------------------------------------

def test_cases_without_spans_are_excluded_from_that_metric():
    """A round-trip-only case must not inflate precision or recall to 1.0."""
    masker = StubMasker({"Sam": "[CHILD_A]"})
    results = [
        score_mask_case(masker, {"id": "leaky", "text": "Pat here", "must_mask": ["Pat"]}),
        score_mask_case(masker, {"id": "roundtrip_only", "text": "Sam here"}),
    ]
    metrics = aggregate_mask_results(results)
    # Only the first case declares must_mask, and it leaks -> 0.0, not 0.5.
    assert metrics["mask_recall"] == 0.0
    assert metrics["mask_precision"] == 0.0  # no case declares must_not_mask
    assert metrics["mask_roundtrip_fidelity"] == 1.0


# --- name resolution -------------------------------------------------------

def _resolver(extracted, children):
    """Minimal stand-in: exact match only."""
    names = [c["name"] for c in children]
    for name in names:
        if (extracted or "").casefold() == name.casefold():
            return {"extracted": extracted, "resolved": name, "matched": True, "method": "exact"}
    return {"extracted": extracted, "resolved": extracted or "", "matched": False, "method": "none"}


def test_name_resolution_expected_match():
    case = {"id": "n", "extracted": "sam", "expected_resolved": "Sam", "expected_matched": True}
    assert score_name_resolution_case(_resolver, case, [{"name": "Sam"}])["passed"] is True


def test_unknown_child_must_stay_unmatched():
    """expected_matched=False is a real expectation, not an absence of one.

    Coercing an unfamiliar camper onto a sibling's schedule is worse than
    leaving it unmatched, because the warning path never fires.
    """
    case = {
        "id": "n",
        "extracted": "Priya",
        "expected_resolved": "Priya",
        "expected_matched": False,
    }
    assert score_name_resolution_case(_resolver, case, [{"name": "Sam"}])["passed"] is True

    bad_resolver = lambda e, c: {  # noqa: E731 - always coerces to the first child
        "extracted": e, "resolved": c[0]["name"], "matched": True, "method": "exact",
    }
    assert score_name_resolution_case(bad_resolver, case, [{"name": "Sam"}])["passed"] is False


def test_aggregate_name_resolution():
    rows = [{"passed": True}, {"passed": False}, {"passed": True}, {"passed": True}]
    assert aggregate_name_resolution(rows)["name_resolution_accuracy"] == 0.75


def test_group_failures_ranks_worst_family_first():
    rows = [
        {"id": "a", "family": "collision", "passed": False},
        {"id": "b", "family": "collision", "passed": False},
        {"id": "c", "family": "surname", "passed": False},
        {"id": "d", "family": "surname", "passed": True},
    ]
    grouped = group_failures(rows)
    assert list(grouped) == ["collision", "surname"]
    assert grouped["collision"] == ["a", "b"]
    assert grouped["surname"] == ["c"]
