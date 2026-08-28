"""Deterministic scoring functions for the eval harness.

No LLM-as-a-judge is used here: every metric is computed with exact matching
or string-similarity ratios so that scores are reproducible for a given set
of model outputs.
"""
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

# Weights for the registration interpreter field score. Must sum to 1.0.
REGISTRATION_FIELD_WEIGHTS = {
    "child_name": 0.25,
    "start_date": 0.15,
    "end_date": 0.15,
    "start_time": 0.125,
    "end_time": 0.125,
    "activity_title": 0.10,
    "location": 0.05,
    "notes": 0.05,
}

# Weights for the disruption interpreter field score. Must sum to 1.0.
DISRUPTION_FIELD_WEIGHTS = {
    "child_name": 0.35,
    "date": 0.30,
    "disruption_type": 0.20,
    "description": 0.15,
}

FUZZY_MATCH_THRESHOLD = 0.55


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def exact_score(expected: Optional[str], predicted: Optional[str]) -> float:
    return 1.0 if _normalize(expected) == _normalize(predicted) else 0.0


def fuzzy_score(expected: Optional[str], predicted: Optional[str]) -> float:
    """Similarity in [0, 1]. Substring containment counts as a full match."""
    exp, pred = _normalize(expected), _normalize(predicted)
    if not exp and not pred:
        return 1.0
    if not exp or not pred:
        return 0.0
    if exp in pred or pred in exp:
        return 1.0
    return SequenceMatcher(None, exp, pred).ratio()


def name_score(expected: Optional[str], predicted: Optional[str]) -> float:
    """Score a person-name field: 1.0 on exact match, or when every expected
    name token appears as a whole word in the prediction, else 0.0.

    Profiles store first names ("Emily") while emails often carry full names
    ("Emily Smith"); extracting the fuller form is correct behavior, not an
    error. Word-level containment (rather than substring) avoids false
    positives between similar sibling names (e.g. "Emma" vs "Emmanuel").
    """
    exp, pred = _normalize(expected), _normalize(predicted)
    if exp == pred:
        return 1.0
    if not exp or not pred:
        return 0.0
    expected_tokens = set(exp.split())
    predicted_tokens = set(pred.split())
    return 1.0 if expected_tokens <= predicted_tokens else 0.0


def score_triager_case(expected_category: str, predicted_category: str) -> float:
    return exact_score(expected_category, predicted_category)


def score_registration_activity(expected: Dict[str, Any], predicted: Dict[str, Any]) -> Dict[str, Any]:
    """Score one extracted activity against manifest ground truth.

    Exact-match fields: dates, times.
    Name field: child name (exact or whole-word containment, see name_score).
    Fuzzy fields: activity title, location, notes (gated by FUZZY_MATCH_THRESHOLD
    so a near-miss is scored by its similarity ratio and a clear miss scores 0).
    """
    field_scores: Dict[str, float] = {
        "child_name": name_score(expected.get("child_name"), predicted.get("child_name")),
    }

    for field in ("start_date", "end_date", "start_time", "end_time"):
        field_scores[field] = exact_score(expected.get(field), predicted.get(field))

    for field in ("activity_title", "location", "notes"):
        ratio = fuzzy_score(expected.get(field), predicted.get(field))
        field_scores[field] = ratio if ratio >= FUZZY_MATCH_THRESHOLD else 0.0

    total = sum(REGISTRATION_FIELD_WEIGHTS[f] * s for f, s in field_scores.items())
    return {"field_scores": field_scores, "score": round(total, 4)}


def score_disruption(expected: Dict[str, Any], predicted: Dict[str, Any]) -> Dict[str, Any]:
    field_scores: Dict[str, float] = {
        "child_name": name_score(expected.get("child_name"), predicted.get("child_name")),
        "date": exact_score(expected.get("date"), predicted.get("date")),
        "disruption_type": exact_score(expected.get("disruption_type"), predicted.get("disruption_type")),
    }
    ratio = fuzzy_score(expected.get("description"), predicted.get("description"))
    field_scores["description"] = ratio if ratio >= FUZZY_MATCH_THRESHOLD else 0.0

    total = sum(DISRUPTION_FIELD_WEIGHTS[f] * s for f, s in field_scores.items())
    return {"field_scores": field_scores, "score": round(total, 4)}


def pick_best_activity(expected: Dict[str, Any], activities: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """From a list of extracted activities, pick the one that best matches the
    expected ground truth (the interpreter may legitimately extract several)."""
    if not activities:
        return None
    scored = [(score_registration_activity(expected, act)["score"], i) for i, act in enumerate(activities)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return activities[scored[0][1]]


def aggregate(scores: List[float]) -> float:
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


# ---------------------------------------------------------------------------
# Multi-activity scoring
# ---------------------------------------------------------------------------
# `pick_best_activity` above scores a single expected activity against the
# best-matching prediction. That is correct for the one-child/one-activity
# fixtures, but it is blind in both directions once an email carries more than
# one activity: extracting 1 of 2 expected activities still scores 1.0 on the
# one it found, and hallucinating four extra activities alongside a correct one
# also scores 1.0. Neither a miss nor an invention costs anything.
#
# The functions below score the *set*, so both failure modes are paid for.

# A pair must clear this to count as the same activity. Below it, the pair is
# scored as a miss plus a spurious extraction rather than a poor match, which
# keeps one badly-wrong prediction from masking a genuinely missing activity.
ACTIVITY_MATCH_THRESHOLD = 0.5


def match_activities(
    expected: List[Dict[str, Any]], predicted: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Greedily assign predicted activities to expected ones, one-to-one.

    Every pair is scored with ``score_registration_activity``; the highest
    scoring pairs are assigned first, and each expected and predicted activity
    is consumed at most once. Ties break on index order so the result is
    deterministic for a given set of model outputs, matching the rest of this
    module's no-LLM-judge contract.

    Greedy assignment (rather than optimal Hungarian matching) is deliberate:
    activity counts here are single digits, the two agree in practice at these
    sizes, and greedy keeps the result trivially explainable in a report.
    """
    candidates = []
    for ei, exp in enumerate(expected):
        for pi, pred in enumerate(predicted):
            score = score_registration_activity(exp, pred)["score"]
            candidates.append((score, ei, pi))
    # -score for descending quality; ei/pi ascending for a stable tie-break.
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_expected: set = set()
    used_predicted: set = set()
    pairs: List[Dict[str, Any]] = []
    for score, ei, pi in candidates:
        if ei in used_expected or pi in used_predicted:
            continue
        if score < ACTIVITY_MATCH_THRESHOLD:
            continue
        used_expected.add(ei)
        used_predicted.add(pi)
        pairs.append({"expected_index": ei, "predicted_index": pi, "score": score})

    missed = [i for i in range(len(expected)) if i not in used_expected]
    spurious = [i for i in range(len(predicted)) if i not in used_predicted]

    n_matched = len(pairs)
    precision = n_matched / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = n_matched / len(expected) if expected else (1.0 if not predicted else 0.0)
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "pairs": pairs,
        "missed_expected": missed,
        "spurious_predicted": spurious,
        "expected_count": len(expected),
        "predicted_count": len(predicted),
        "activity_precision": round(precision, 4),
        "activity_recall": round(recall, 4),
        "activity_f1": round(f1, 4),
        # Field quality across matched pairs only. Read it together with f1:
        # a high mean with a low f1 means "extracts accurately, but misses
        # activities", which is a different fix from "finds them all, badly".
        "matched_field_score": aggregate([p["score"] for p in pairs]),
    }


def score_activity_set(
    expected: List[Dict[str, Any]], predicted: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Single headline number for a multi-activity case.

    ``f1 * matched_field_score`` — an extraction is only as good as the
    activities it found *and* how accurately it filled them in. Getting one of
    two siblings perfectly right caps the case at 0.5, which is the behavior
    the single-activity scorer could not express.
    """
    result = match_activities(expected, predicted)
    result["score"] = round(result["activity_f1"] * result["matched_field_score"], 4)
    return result
