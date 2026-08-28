"""Deterministic, offline diagnostics for the identity layer.

The identity layer is everything that decides *who* a message is about:

- ``PIIMasker`` (``app/pii_masker.py``) rewrites family names out of the raw
  email before the model ever sees it, and restores them afterwards.
- ``resolve_child_name`` (``app/matrix_logic.py``) maps whatever name the model
  extracted back onto a profile child so the activity lands on the right
  schedule column.

Both are pure Python, so this whole suite runs with **no model calls**: it is
free, exactly reproducible, and cheap enough to gate every pull request. That
matters because a masking defect silently corrupts the text every downstream
LLM metric is computed from -- a bad mask does not look like a masking bug in
the aggregate scores, it looks like a mediocre model.

Scoring is intentionally span-based rather than similarity-based so that a
failure names the exact string that leaked or was mangled.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def _count_occurrences(haystack: str, needle: str, *, ignore_case: bool) -> int:
    if not needle:
        return 0
    flags = re.IGNORECASE if ignore_case else 0
    return len(re.findall(re.escape(needle), haystack or "", flags))


# Placeholders emitted by PIIMasker: [CHILD_A], [PARENT_A], [EMAIL_1],
# [CAREGIVER_PHONE_2], [DYNAMIC_EMAIL_7], [ADDRESS_1] ...
_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9_]*\]")


def find_glued_placeholders(masked: str) -> List[str]:
    """Return placeholders fused to adjacent word characters.

    This is the structural invariant behind the whole substring-collision
    class. A correct mask replaces *whole names*, so a placeholder must never
    be welded to surrounding letters or digits. Every one of these is a
    corrupted word handed to the model:

        "at the [CHILD_B]e time"   <- masked "Sam" inside "same"
        "partici[CHILD_A]ion"      <- masked "Pat" inside "participation"
        "[CHILD_C]andra"           <- masked "Alex" inside "Alexandra"

    Checking the invariant directly means a new profile name that collides
    with a new English word is caught without anyone adding a span for it.
    Legitimate neighbours -- whitespace, punctuation, an apostrophe in
    "[CHILD_B]'s" -- are not word characters and do not trip it.
    """
    glued: List[str] = []
    for m in _PLACEHOLDER.finditer(masked or ""):
        before = masked[m.start() - 1] if m.start() > 0 else ""
        after = masked[m.end()] if m.end() < len(masked) else ""
        if (before and re.match(r"\w", before)) or (after and re.match(r"\w", after)):
            glued.append(masked[max(0, m.start() - 12) : m.end() + 12])
    return glued


def score_mask_case(masker: Any, case: Dict[str, Any]) -> Dict[str, Any]:
    """Score one masking case against its span expectations.

    ``must_mask`` spans are real PII: none may survive in the masked text, in
    any casing. Each surviving span is a **leak**.

    ``must_not_mask`` spans are ordinary English (or third-party names) that
    the masker must leave untouched. The occurrence *count* must be preserved,
    not merely the presence of one instance, so a text containing a span twice
    still fails when only one copy is mangled. Each mangled span is an
    **over-mask** -- the defect that turns "at the same time" into
    "at the [CHILD_B]e time".

    ``expect_roundtrip`` (default true) additionally requires
    ``unmask(mask(text)) == text``.
    """
    text = case.get("text") or ""
    masked = masker.mask(text)

    leaks: List[str] = []
    for span in case.get("must_mask") or []:
        if _count_occurrences(masked, span, ignore_case=True) > 0:
            leaks.append(span)

    over_masked: List[str] = []
    for span in case.get("must_not_mask") or []:
        before = _count_occurrences(text, span, ignore_case=False)
        after = _count_occurrences(masked, span, ignore_case=False)
        if after < before:
            over_masked.append(span)

    n_must_mask = len(case.get("must_mask") or [])
    n_must_not_mask = len(case.get("must_not_mask") or [])

    # Recall: share of true PII spans actually removed.
    recall: Optional[float] = (
        (n_must_mask - len(leaks)) / n_must_mask if n_must_mask else None
    )
    # Precision: share of non-PII spans left intact (inverse over-masking rate).
    precision: Optional[float] = (
        (n_must_not_mask - len(over_masked)) / n_must_not_mask
        if n_must_not_mask
        else None
    )

    roundtrip_expected = case.get("expect_roundtrip", True)
    roundtrip_ok = (masker.unmask(masked) == text) if roundtrip_expected else None

    glued = find_glued_placeholders(masked)

    return {
        "id": case.get("id"),
        "family": case.get("family"),
        "recall": recall,
        "precision": precision,
        "roundtrip_ok": roundtrip_ok,
        "token_integrity_ok": not glued,
        "leaks": leaks,
        "over_masked": over_masked,
        "glued_placeholders": glued,
        "passed": (
            not leaks and not over_masked and not glued and roundtrip_ok is not False
        ),
        "masked_text": masked,
    }


def score_name_resolution_case(
    resolver: Any, case: Dict[str, Any], profile_children: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Score one ``resolve_child_name`` case.

    A case passes when both the resolved name and the matched flag meet
    expectations. ``expected_matched: false`` is a first-class expectation:
    a child who is genuinely not in the profile must stay unmatched so the
    warning path in ``resolve_activity_child_names`` fires, rather than being
    silently coerced onto a sibling's schedule.
    """
    resolution = resolver(case.get("extracted"), profile_children)

    expected_matched = case.get("expected_matched")
    expected_resolved = case.get("expected_resolved")

    matched_ok = (
        resolution["matched"] == expected_matched
        if expected_matched is not None
        else True
    )
    resolved_ok = (
        (resolution["resolved"] or "").strip().casefold()
        == (expected_resolved or "").strip().casefold()
        if expected_resolved is not None
        else True
    )

    return {
        "id": case.get("id"),
        "family": case.get("family"),
        "extracted": case.get("extracted"),
        "expected_resolved": expected_resolved,
        "actual_resolved": resolution["resolved"],
        "expected_matched": expected_matched,
        "actual_matched": resolution["matched"],
        "method": resolution["method"],
        "passed": matched_ok and resolved_ok,
    }


def _mean(values: List[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def aggregate_mask_results(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Roll per-case masking results up into suite metrics.

    Cases that declare no spans of a given kind are excluded from that metric
    rather than counted as a perfect score, so adding round-trip-only cases
    cannot inflate precision or recall.
    """
    recalls = [r["recall"] for r in results if r["recall"] is not None]
    precisions = [r["precision"] for r in results if r["precision"] is not None]
    roundtrips = [
        1.0 if r["roundtrip_ok"] else 0.0
        for r in results
        if r["roundtrip_ok"] is not None
    ]
    integrity = [1.0 if r["token_integrity_ok"] else 0.0 for r in results]
    return {
        "mask_recall": _mean(recalls),
        "mask_precision": _mean(precisions),
        "mask_token_integrity": _mean(integrity),
        "mask_roundtrip_fidelity": _mean(roundtrips),
    }


def aggregate_name_resolution(results: List[Dict[str, Any]]) -> Dict[str, float]:
    return {
        "name_resolution_accuracy": _mean(
            [1.0 if r["passed"] else 0.0 for r in results]
        )
    }


def group_failures(results: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Bucket failing case ids by their declared family, worst bucket first.

    Feeds the ranked findings table in ``insummery-eval diagnose``.
    """
    buckets: Dict[str, List[str]] = {}
    for r in results:
        if r.get("passed"):
            continue
        buckets.setdefault(r.get("family") or "unspecified", []).append(str(r.get("id")))
    return dict(sorted(buckets.items(), key=lambda kv: -len(kv[1])))
