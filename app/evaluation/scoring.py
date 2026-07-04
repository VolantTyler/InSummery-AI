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


def score_triager_case(expected_category: str, predicted_category: str) -> float:
    return exact_score(expected_category, predicted_category)


def score_registration_activity(expected: Dict[str, Any], predicted: Dict[str, Any]) -> Dict[str, Any]:
    """Score one extracted activity against manifest ground truth.

    Exact-match fields: child name, dates, times.
    Fuzzy fields: activity title, location, notes (gated by FUZZY_MATCH_THRESHOLD
    so a near-miss is scored by its similarity ratio and a clear miss scores 0).
    """
    field_scores: Dict[str, float] = {}

    for field in ("child_name", "start_date", "end_date", "start_time", "end_time"):
        field_scores[field] = exact_score(expected.get(field), predicted.get(field))

    for field in ("activity_title", "location", "notes"):
        ratio = fuzzy_score(expected.get(field), predicted.get(field))
        field_scores[field] = ratio if ratio >= FUZZY_MATCH_THRESHOLD else 0.0

    total = sum(REGISTRATION_FIELD_WEIGHTS[f] * s for f, s in field_scores.items())
    return {"field_scores": field_scores, "score": round(total, 4)}


def score_disruption(expected: Dict[str, Any], predicted: Dict[str, Any]) -> Dict[str, Any]:
    field_scores: Dict[str, float] = {
        "child_name": exact_score(expected.get("child_name"), predicted.get("child_name")),
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
