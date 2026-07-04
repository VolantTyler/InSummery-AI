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
