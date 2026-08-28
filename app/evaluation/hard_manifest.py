"""Loader for the hard-suite manifest.

Year-less date ranges are one of the things the interpreter is supposed to get
right (`_today_context()` in app/agent_factories.py encodes the rule), but
ground truth for such a case cannot be a fixed string -- the correct answer
moves with the calendar. Rather than pin the clock, the manifest declares the
rule and this module applies it, so the case keeps testing real behavior and
stays reproducible as the year rolls over.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


def season_year(range_end: str, today: Optional[datetime.date] = None) -> int:
    """Year for a year-less range, per the rule the prompt gives the model.

    Keep the current calendar year unless the range has already fully ended,
    in which case the message must be about next year's season.

    ``range_end`` is the MM-DD the range closes on.
    """
    today = today or datetime.date.today()
    month, day = (int(p) for p in range_end.split("-"))
    try:
        end_this_year = datetime.date(today.year, month, day)
    except ValueError:  # Feb 29 in a non-leap year
        end_this_year = datetime.date(today.year, month, day - 1)
    return today.year if end_this_year >= today else today.year + 1


def _resolve_tokens(value: Any, year: int) -> Any:
    if isinstance(value, str) and "{Y}" in value:
        return value.replace("{Y}", str(year))
    return value


def resolve_case(case: Dict[str, Any], today: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Return the case with every ``{Y}`` token replaced by the resolved year.

    Cases with no ``date_resolution`` block are returned unchanged.
    """
    rule = (case.get("date_resolution") or {}).get("rule")
    if rule != "season_year":
        return case

    year = season_year(case["date_resolution"]["range_end"], today=today)
    resolved = dict(case)
    resolved["expected_activities"] = [
        {k: _resolve_tokens(v, year) for k, v in act.items()}
        for act in case.get("expected_activities", [])
    ]
    resolved["_resolved_year"] = year
    return resolved


def load_cases(
    manifest: Dict[str, Any],
    axes: Optional[List[str]] = None,
    today: Optional[datetime.date] = None,
) -> List[Dict[str, Any]]:
    """Load manifest cases, optionally filtered to specific axes."""
    cases = [resolve_case(c, today=today) for c in manifest.get("cases", [])]
    if axes:
        wanted = set(axes)
        cases = [c for c in cases if c.get("axis") in wanted]
    return cases
