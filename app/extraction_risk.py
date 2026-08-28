"""Deterministic escalation signals for the human-in-the-loop gate.

The production gate pauses for a human when the model's self-reported
``confidence_score`` falls below 80. Measured over 29 eval cases, that score
took exactly three values -- 95, 98 and 100 -- so the gate fired zero times.
On the one case where the extraction attached the activity to the wrong child,
the model reported confidence 100 and a trace asserting the child's name was
clearly provided (see tests/eval/FINDINGS.md, Finding 0).

A self-report the model can be confidently wrong about is not a safety
mechanism. These checks look at the *extraction itself* instead: they are pure
functions of the output, the family profile and the source text, so they cannot
be talked out of firing.

Design constraint: escalate on consequence, not on uncertainty. Every false
escalation costs a parent an interruption, so each check below corresponds to a
specific way the schedule would end up wrong -- an activity on nobody's
calendar, a missing time, a placeholder written into saved data. Signals that
are merely *suspicious* are deliberately excluded.

Deliberately NOT checked, having been tried and removed:

- *Range already ended.* Intended to catch year-inference errors, but it fires
  on any legitimately old email (importing a past season, re-processing an
  archive) while the consequence is mild -- a past-dated activity just sits in
  history. Poor precision, modest consequence: exactly what the rule above
  says to exclude. A year-inference error that lands in the *future* is caught
  by ``date_range_implausibly_far`` instead.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional

from app.matrix_logic import resolve_child_name

# Fields without which the activity cannot be placed on a schedule at all.
REQUIRED_ACTIVITY_FIELDS = (
    "child_name",
    "activity_title",
    "start_date",
    "end_date",
    "start_time",
    "end_time",
)

# An unresolved placeholder that reached an output field means the mask/unmask
# round-trip failed and a token like "[CHILD_A]" is about to be persisted.
_BRACKETED_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9_]*\]")
_BARE_PLACEHOLDER = re.compile(
    r"\b(?:CHILD|PARENT|CAREGIVER|ADDRESS|EMAIL|PHONE|DYNAMIC)_[A-Z0-9_]+\b"
)

# A date range this far out is more likely a year-inference error than a real
# booking. Camps are published a season ahead, not two years.
MAX_PLAUSIBLE_MONTHS_AHEAD = 18


def _as_dict(activity: Any) -> Dict[str, Any]:
    return activity.model_dump() if hasattr(activity, "model_dump") else (activity or {})


def _parse_iso(value: Optional[str]) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat((value or "").strip())
    except (ValueError, AttributeError):
        return None


def _placeholder_fields(activity: Dict[str, Any]) -> List[str]:
    hits = []
    for field in ("child_name", "activity_title", "location", "notes"):
        value = activity.get(field)
        if not isinstance(value, str) or not value:
            continue
        if _BRACKETED_PLACEHOLDER.search(value) or _BARE_PLACEHOLDER.search(value):
            hits.append(field)
    return hits


def assess_activity(
    activity: Any,
    profile_children: List[Dict[str, Any]],
    today: Optional[datetime.date] = None,
) -> List[Dict[str, Any]]:
    """Return escalation reasons for a single extracted activity."""
    today = today or datetime.date.today()
    act = _as_dict(activity)
    reasons: List[Dict[str, Any]] = []

    missing = [f for f in REQUIRED_ACTIVITY_FIELDS if not (act.get(f) or "").strip()]
    if missing:
        reasons.append(
            {
                "code": "missing_required_field",
                "detail": f"missing {', '.join(missing)}",
                "fields": missing,
            }
        )

    # An extracted name that matches no child in the profile means the activity
    # silently lands on nobody's schedule column. This is the exact failure the
    # model reported confidence 100 on.
    name = (act.get("child_name") or "").strip()
    if name and profile_children:
        resolution = resolve_child_name(name, profile_children)
        if not resolution["matched"]:
            known = ", ".join(
                c.get("name") for c in profile_children if isinstance(c, dict) and c.get("name")
            )
            reasons.append(
                {
                    "code": "unresolved_child_name",
                    "detail": f"'{name}' does not match a child in the profile ({known})",
                    "extracted": name,
                }
            )

    leaked = _placeholder_fields(act)
    if leaked:
        reasons.append(
            {
                "code": "placeholder_leak",
                "detail": f"unresolved PII placeholder in {', '.join(leaked)}",
                "fields": leaked,
            }
        )

    start, end = _parse_iso(act.get("start_date")), _parse_iso(act.get("end_date"))
    if start and end:
        if end < start:
            reasons.append(
                {
                    "code": "inverted_date_range",
                    "detail": f"end date {end} precedes start date {start}",
                }
            )
        elif (start - today).days > MAX_PLAUSIBLE_MONTHS_AHEAD * 30:
            reasons.append(
                {
                    "code": "date_range_implausibly_far",
                    "detail": f"starts {start}, more than {MAX_PLAUSIBLE_MONTHS_AHEAD} months out",
                }
            )
    return reasons


def assess_extraction(
    activities: Optional[List[Any]],
    profile_children: Optional[List[Dict[str, Any]]] = None,
    guardrail: Optional[Dict[str, Any]] = None,
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Decide whether an extraction must be escalated to a human.

    Independent of ``confidence_score`` by design -- this is the check that
    still works when the model is confidently wrong.
    """
    reasons: List[Dict[str, Any]] = []

    if not activities:
        reasons.append(
            {"code": "no_activities", "detail": "the extraction produced no activities"}
        )

    for index, activity in enumerate(activities or []):
        for reason in assess_activity(activity, profile_children or [], today=today):
            reasons.append({**reason, "activity_index": index})

    # The guardrail result was already computed in interpreter_registration_node
    # and recorded for tracing, but nothing acted on it.
    if guardrail and not guardrail.get("passed", True):
        violations = list(guardrail.get("violations") or [])
        reasons.append(
            {
                "code": "guardrail_failed",
                "detail": f"guardrail violations: {', '.join(violations) or 'unspecified'}",
                "violations": violations,
            }
        )

    return {
        "escalate": bool(reasons),
        "reasons": reasons,
        "codes": sorted({r["code"] for r in reasons}),
    }


def describe_for_human(assessment: Dict[str, Any]) -> str:
    """Turn an assessment into the question shown to the parent.

    Names the concrete problem rather than a confidence percentage, because
    "I am 62% sure" is not something a parent can act on, while "this says
    Sammy and your children are Sam and Pat" is.
    """
    reasons = assessment.get("reasons") or []
    if not reasons:
        return "Please confirm the schedule details."
    bullets = "\n".join(f"- {r['detail']}" for r in reasons)
    return (
        "This registration needs your confirmation before it goes on the "
        f"schedule:\n{bullets}\n\nPlease clarify the correct details."
    )
