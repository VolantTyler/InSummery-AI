import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.name_aliases import names_equivalent


def parse_date(date_str: str) -> datetime.date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


_NAME_SPLIT = re.compile(r"\s+")
_POSSESSIVE_SUFFIX = re.compile(r"['’]s$", re.IGNORECASE)


def _normalize_person_name(value: Optional[str]) -> str:
    if not value or not isinstance(value, str):
        return ""
    return _NAME_SPLIT.sub(" ", value.strip()).casefold()


def _name_tokens(value: str) -> List[str]:
    return [t for t in _normalize_person_name(value).split(" ") if t]


def _strip_possessive(value: str) -> str:
    """Strip a trailing possessive ("Riley's" -> "Riley") before matching."""
    return _POSSESSIVE_SUFFIX.sub("", value)


def _safe_replace_year(value: datetime.date, year: int) -> datetime.date:
    """Shift a date to ``year``, clamping Feb 29 → Feb 28 when needed."""
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


def normalize_activity_dates(
    activity: Dict[str, Any],
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Prefer the current calendar year for year-less seasonal ranges.

    Interpreters sometimes follow "nearest future date" too literally and push
    an ongoing summer camp (start already passed, end still ahead) into next
    year. If shifting start/end into ``today.year`` keeps the range ongoing or
    upcoming (end >= today), use the current year.
    """
    today = today or datetime.now().date()
    start_raw = activity.get("start_date")
    end_raw = activity.get("end_date")
    if not start_raw or not end_raw:
        return activity

    try:
        start = parse_date(start_raw)
        end = parse_date(end_raw)
    except (TypeError, ValueError):
        return activity

    if end < start:
        return activity

    current_year = today.year
    if start.year == current_year and end.year == current_year:
        return activity

    # Fully in the past for the stated years → bump forward until end >= today.
    if end < today:
        shifted = dict(activity)
        years_ahead = 0
        new_start, new_end = start, end
        while new_end < today and years_ahead < 5:
            years_ahead += 1
            new_start = _safe_replace_year(start, start.year + years_ahead)
            new_end = _safe_replace_year(end, end.year + years_ahead)
        shifted["start_date"] = new_start.strftime("%Y-%m-%d")
        shifted["end_date"] = new_end.strftime("%Y-%m-%d")
        return shifted

    # Future-year range that would still be active/upcoming in the current year.
    if start.year > current_year or end.year > current_year:
        try_start = _safe_replace_year(start, current_year)
        try_end = _safe_replace_year(end, current_year)
        if try_end >= try_start and try_end >= today:
            shifted = dict(activity)
            shifted["start_date"] = try_start.strftime("%Y-%m-%d")
            shifted["end_date"] = try_end.strftime("%Y-%m-%d")
            return shifted

    return activity


def normalize_activities_dates(
    activities: List[Dict[str, Any]],
    today: Optional[datetime.date] = None,
) -> List[Dict[str, Any]]:
    """Apply :func:`normalize_activity_dates` to each activity dict."""
    return [normalize_activity_dates(act, today=today) for act in activities]


def resolve_child_name(
    extracted: Optional[str],
    profile_children: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Map an extracted child name onto a profile child's canonical name.

    The matrix UI matches activities with strict equality against
    ``profile.children[].name``. Emails often use fuller forms
    (``Sam Smith``) while the profile stores a first name (``Sam``).

    Matching order (first unique hit wins):
    1. Exact case-insensitive match
    2. Unique profile first-name equals the extracted first token
    3. Unique profile whose tokens are all whole-word contained in the
       extracted name (or vice versa), preferring the longest profile name

    Returns a dict with ``resolved`` (name to store), ``matched`` (bool),
    ``method`` (``exact`` / ``first_name`` / ``token_containment`` / ``none``),
    and ``extracted`` (original string).
    """
    raw = _strip_possessive((extracted or "").strip())
    children = [
        c.get("name")
        for c in (profile_children or [])
        if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("name").strip()
    ]
    result = {
        "extracted": raw,
        "resolved": raw,
        "matched": False,
        "method": "none",
    }
    if not raw:
        return result
    if not children:
        return result

    extracted_norm = _normalize_person_name(raw)
    extracted_tokens = _name_tokens(raw)

    # 1) Exact (case-insensitive, or a known nickname) → profile's stored casing.
    exact = [
        name
        for name in children
        if _normalize_person_name(name) == extracted_norm or names_equivalent(name, raw)
    ]
    if len(exact) == 1:
        result.update({"resolved": exact[0], "matched": True, "method": "exact"})
        return result
    if len(exact) > 1:
        # Ambiguous identical profile names — keep extracted.
        return result

    # 2) Unique first-name match (nicknames included): profile "Sam" ←
    #    extracted "Sam Smith" or "Sammy Smith".
    if extracted_tokens:
        first = extracted_tokens[0]
        first_hits = [
            name
            for name in children
            if names_equivalent((_name_tokens(name)[:1] or [None])[0] or "", first)
        ]
        if len(first_hits) == 1:
            result.update(
                {"resolved": first_hits[0], "matched": True, "method": "first_name"}
            )
            return result

    # 3) Token containment either direction; prefer longest unique profile name.
    containment: List[Tuple[int, str]] = []
    extracted_set = set(extracted_tokens)
    for name in children:
        profile_tokens = _name_tokens(name)
        if not profile_tokens:
            continue
        profile_set = set(profile_tokens)
        if profile_set <= extracted_set or extracted_set <= profile_set:
            containment.append((len(name), name))
    if containment:
        containment.sort(key=lambda item: item[0], reverse=True)
        best_len, best_name = containment[0]
        ties = [n for length, n in containment if length == best_len]
        if len(ties) == 1:
            result.update(
                {"resolved": best_name, "matched": True, "method": "token_containment"}
            )
            return result

    return result


def resolve_activity_child_names(
    activities: List[Dict[str, Any]],
    profile_children: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Resolve each activity's ``child_name`` onto the profile; collect warnings."""
    resolved_activities: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for act in activities:
        act_copy = dict(act)
        resolution = resolve_child_name(act_copy.get("child_name"), profile_children)
        act_copy["child_name"] = resolution["resolved"]
        if resolution["matched"] and resolution["method"] != "exact":
            warnings.append(
                f"Matched extracted child name '{resolution['extracted']}' "
                f"to profile child '{resolution['resolved']}'."
            )
        elif not resolution["matched"] and resolution["extracted"]:
            profile_names = ", ".join(
                c.get("name")
                for c in (profile_children or [])
                if isinstance(c, dict) and c.get("name")
            ) or "(none)"
            warnings.append(
                f"Could not match child name '{resolution['extracted']}' to a "
                f"profile child ({profile_names}). The activity was saved but "
                f"may not appear on the schedule until the name matches."
            )
        resolved_activities.append(act_copy)
    return resolved_activities, warnings

def parse_time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 60 + m

def minutes_to_time_str(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def get_day_of_week(date_obj: datetime.date) -> str:
    return date_obj.strftime("%A")

def get_month_name(date_obj: datetime.date) -> str:
    return date_obj.strftime("%B")

def _baseline_days(baseline: Dict[str, Any]) -> List[Any]:
    """Return the configured baseline weekdays from supported schema variants.

    The frontend stores numeric JS weekdays in ``days`` (0=Sunday, 1=Monday),
    older MatrixGrid code looked for ``days_of_week``, and the original backend
    expected day names in ``days``. Accept all three so existing profiles and
    newly onboarded profiles evaluate consistently.
    """
    return baseline.get("days") or baseline.get("days_of_week") or []


def _baseline_matches_day(date_obj: datetime.date, baseline: Dict[str, Any]) -> bool:
    days = _baseline_days(baseline)
    if not days:
        return True

    day_name = get_day_of_week(date_obj)
    js_day_number = (date_obj.weekday() + 1) % 7

    for configured_day in days:
        if isinstance(configured_day, str):
            if configured_day.lower() == day_name.lower():
                return True
            if configured_day.isdigit() and int(configured_day) == js_day_number:
                return True
        elif configured_day == js_day_number:
            return True

    return False


def _baseline_matches_date_range(date_obj: datetime.date, baseline: Dict[str, Any]) -> bool:
    """Return whether ``date_obj`` falls in a baseline's active date span.

    Prefer the frontend's explicit ``start_date``/``end_date`` schema. Fall back
    to the backend's legacy ``months`` list when no explicit date range exists.
    """
    start_date = baseline.get("start_date")
    end_date = baseline.get("end_date")

    if start_date or end_date:
        if start_date and date_obj < parse_date(start_date):
            return False
        if end_date and date_obj > parse_date(end_date):
            return False
        return True

    months = baseline.get("months")
    if months:
        month = get_month_name(date_obj)
        return any(isinstance(m, str) and m.lower() == month.lower() for m in months)

    return True


def is_date_in_baseline(date_obj: datetime.date, baseline: Dict[str, Any]) -> bool:
    return _baseline_matches_date_range(date_obj, baseline) and _baseline_matches_day(date_obj, baseline)

def calculate_gaps(activities: List[Dict[str, Any]], profile: Dict[str, Any], start_date: datetime.date, end_date: datetime.date) -> List[Dict[str, Any]]:
    """
    Calculate absolute and relative childcare gaps for each child between start_date and end_date.
    Uses a minute-by-minute coverage grid for each day (9:00 AM to 5:00 PM / 540 to 1020 minutes).
    """
    gaps = []
    children = [c.get("name") for c in profile.get("children", []) if c.get("name")]
    baselines = profile.get("baseline_coverage", [])
    
    # Define the care window: 9:00 AM to 5:00 PM
    start_min = 540  # 9:00
    end_min = 1020   # 17:00
    total_minutes = end_min - start_min

    current_date = start_date
    while current_date <= end_date:
        # We only analyze weekdays (Monday to Friday)
        if current_date.weekday() < 5: 
            day_str = current_date.strftime("%Y-%m-%d")
            day_of_week = get_day_of_week(current_date)
            
            # Minute-by-minute coverage grid for each child
            # False means uncovered (gap), True means covered
            coverage: Dict[str, List[bool]] = {child: [False] * total_minutes for child in children}
            
            # 1. Populate coverage from baseline (e.g. school)
            for baseline in baselines:
                if is_date_in_baseline(current_date, baseline):
                    b_start = parse_time_to_minutes(baseline.get("start_time", "08:30"))
                    b_end = parse_time_to_minutes(baseline.get("end_time", "15:00"))
                    
                    # Map to our 9:00-17:00 window
                    for m in range(start_min, end_min):
                        if b_start <= m < b_end:
                            idx = m - start_min
                            for child in children:
                                coverage[child][idx] = True

            # 2. Populate coverage from active activities
            for act in activities:
                if act.get("status") != "ACTIVE":
                    continue
                
                act_start_date = parse_date(act["start_date"])
                act_end_date = parse_date(act["end_date"])
                
                if act_start_date <= current_date <= act_end_date:
                    child = act.get("child_name")
                    if child in coverage:
                        a_start = parse_time_to_minutes(act["start_time"])
                        a_end = parse_time_to_minutes(act["end_time"])
                        
                        for m in range(start_min, end_min):
                            if a_start <= m < a_end:
                                idx = m - start_min
                                coverage[child][idx] = True

            # 3. Detect Absolute Gaps per child
            for child in children:
                in_gap = False
                gap_start = None
                
                for idx in range(total_minutes):
                    is_covered = coverage[child][idx]
                    m = idx + start_min
                    
                    if not is_covered and not in_gap:
                        in_gap = True
                        gap_start = m
                    elif is_covered and in_gap:
                        in_gap = False
                        gaps.append({
                            "child_name": child,
                            "date": day_str,
                            "start_time": minutes_to_time_str(gap_start),
                            "end_time": minutes_to_time_str(m),
                            "type": "ABSOLUTE",
                            "description": f"No care scheduled for {child}."
                        })
                
                if in_gap:
                    gaps.append({
                        "child_name": child,
                        "date": day_str,
                        "start_time": minutes_to_time_str(gap_start),
                        "end_time": minutes_to_time_str(end_min),
                        "type": "ABSOLUTE",
                        "description": f"No care scheduled for {child}."
                    })

            # 4. Detect Relative Gaps (Sibling Mismatch)
            # A relative gap occurs when one sibling is covered by an activity (not school)
            # but another sibling has an absolute gap during that same time.
            if len(children) > 1:
                for child_a in children:
                    for child_b in children:
                        if child_a == child_b:
                            continue
                        
                        # Find times where child_a is at a camp/activity (not school)
                        # and child_b has an absolute gap
                        in_rel_gap = False
                        rel_gap_start = None
                        
                        for idx in range(total_minutes):
                            m = idx + start_min
                            
                            # Check if child_a has an active activity at this minute
                            child_a_active = False
                            for act in activities:
                                if act.get("status") == "ACTIVE" and act.get("child_name") == child_a:
                                    act_start_date = parse_date(act["start_date"])
                                    act_end_date = parse_date(act["end_date"])
                                    if act_start_date <= current_date <= act_end_date:
                                        a_start = parse_time_to_minutes(act["start_time"])
                                        a_end = parse_time_to_minutes(act["end_time"])
                                        if a_start <= m < a_end:
                                            child_a_active = True
                                            break
                            
                            # Child_b has an absolute gap
                            child_b_gap = not coverage[child_b][idx]
                            
                            is_rel_gap_min = child_a_active and child_b_gap
                            
                            if is_rel_gap_min and not in_rel_gap:
                                in_rel_gap = True
                                rel_gap_start = m
                            elif not is_rel_gap_min and in_rel_gap:
                                in_rel_gap = False
                                gaps.append({
                                    "child_name": child_b,
                                    "date": day_str,
                                    "start_time": minutes_to_time_str(rel_gap_start),
                                    "end_time": minutes_to_time_str(m),
                                    "type": "RELATIVE",
                                    "description": f"Sibling mismatch: {child_a} has an activity, but {child_b} has no care."
                                })
                        
                        if in_rel_gap:
                            gaps.append({
                                "child_name": child_b,
                                "date": day_str,
                                "start_time": minutes_to_time_str(rel_gap_start),
                                "end_time": minutes_to_time_str(end_min),
                                "type": "RELATIVE",
                                "description": f"Sibling mismatch: {child_a} has an activity, but {child_b} has no care."
                            })

        current_date += timedelta(days=1)
        
    return gaps

def merge_activities(current_matrix: Dict[str, Any], new_activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge new activities into the current matrix, avoiding duplicates."""
    updated_activities = list(current_matrix.get("activities", []))
    
    for new_act in new_activities:
        # Simple deduplication check: same child, title, date range, and times
        duplicate = False
        for act in updated_activities:
            if (act.get("child_name") == new_act.get("child_name") and
                act.get("activity_title") == new_act.get("activity_title") and
                act.get("start_date") == new_act.get("start_date") and
                act.get("end_date") == new_act.get("end_date") and
                act.get("start_time") == new_act.get("start_time") and
                act.get("end_time") == new_act.get("end_time")):
                # Update status to ACTIVE if it was disrupted/cancelled
                act["status"] = "ACTIVE"
                duplicate = True
                break
        
        if not duplicate:
            act_copy = dict(new_act)
            if "id" not in act_copy:
                act_copy["id"] = str(uuid.uuid4())[:8]
            act_copy["status"] = "ACTIVE"
            updated_activities.append(act_copy)
            
    return {"activities": updated_activities, "gaps": []}

def _normalize_disruption_field(value: Any) -> str:
    """Treat placeholder junk the LLM may emit (e.g. 'N/A') as unspecified."""
    if not value or not isinstance(value, str):
        return ""
    if value.strip().lower() in ("n/a", "na", "none", "unknown", "unspecified"):
        return ""
    return value.strip()


def _titles_match(disruption_title: str, activity_title: str) -> bool:
    a, b = disruption_title.lower(), (activity_title or "").lower()
    return bool(a and b) and (a in b or b in a)


def apply_disruption(current_matrix: Dict[str, Any], disruption: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a disruption (e.g. cancellation) to the matrix.

    An activity is disrupted when the disruption date/time overlaps it AND it
    matches the identifying details the message provided: the child's name,
    the activity title, or both. If the message identifies neither, nothing
    is changed (rather than guessing and disrupting everything); the caller
    surfaces a warning instead.
    """
    updated_activities = list(current_matrix.get("activities", []))
    disrupted_child = _normalize_disruption_field(disruption.get("child_name"))
    disruption_title = _normalize_disruption_field(disruption.get("activity_title"))
    disruption_date = disruption.get("date")

    if not disrupted_child and not disruption_title:
        return {"activities": updated_activities, "gaps": []}

    dis_start = parse_time_to_minutes(disruption.get("start_time", "00:00") or "00:00")
    dis_end = parse_time_to_minutes(disruption.get("end_time", "23:59") or "23:59")

    for act in updated_activities:
        if disrupted_child and act.get("child_name") != disrupted_child:
            continue
        if disruption_title and not _titles_match(disruption_title, act.get("activity_title")):
            continue

        act_start_date = parse_date(act["start_date"])
        act_end_date = parse_date(act["end_date"])
        target_date = parse_date(disruption_date)

        if act_start_date <= target_date <= act_end_date:
            # Check if times overlap
            act_start = parse_time_to_minutes(act["start_time"])
            act_end = parse_time_to_minutes(act["end_time"])

            # Overlap check
            if max(act_start, dis_start) < min(act_end, dis_end):
                act["status"] = "DISRUPTED"
                act["notes"] = f"{act.get('notes', '')} [DISRUPTED: {disruption.get('description')}]".strip()

    return {"activities": updated_activities, "gaps": []}


def delete_activity(matrix: Dict[str, Any], activity_id: str, delete_type: str, date_str: str = None) -> Dict[str, Any]:
    """Delete a single event or entire series from the matrix.

    Args:
        matrix: The schedule matrix dict with "activities" and optionally "deleted_google_event_ids".
        activity_id: The ID of the activity to delete.
        delete_type: "single" to remove one date, "series" to remove the whole activity.
        date_str: Required when delete_type is "single". The YYYY-MM-DD date to remove.

    Returns:
        The mutated matrix dict, or raises ValueError on bad input / activity not found.
    """
    activities = matrix.get("activities", [])

    # Find the activity
    activity_idx = -1
    for i, act in enumerate(activities):
        if act.get("id") == activity_id:
            activity_idx = i
            break

    if activity_idx == -1:
        raise ValueError(f"Activity with ID {activity_id} not found")

    act = activities[activity_idx]

    if delete_type == "series":
        google_event_id = act.get("google_event_id")
        if google_event_id:
            if "deleted_google_event_ids" not in matrix:
                matrix["deleted_google_event_ids"] = []
            matrix["deleted_google_event_ids"].append(google_event_id)
        activities.pop(activity_idx)

    elif delete_type == "single":
        if not date_str:
            raise ValueError("Missing date parameter for single event deletion")

        start_date_str = act.get("start_date")
        end_date_str = act.get("end_date")

        if start_date_str == end_date_str:
            # Single-day activity → remove entirely
            google_event_id = act.get("google_event_id")
            if google_event_id:
                if "deleted_google_event_ids" not in matrix:
                    matrix["deleted_google_event_ids"] = []
                matrix["deleted_google_event_ids"].append(google_event_id)
            activities.pop(activity_idx)
        elif date_str == start_date_str:
            dt = datetime.strptime(start_date_str, "%Y-%m-%d")
            act["start_date"] = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_str == end_date_str:
            dt = datetime.strptime(end_date_str, "%Y-%m-%d")
            act["end_date"] = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            # Split the activity into two halves around date_str
            target_dt = datetime.strptime(date_str, "%Y-%m-%d")
            part1_end = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            part2_start = (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")

            # Copy before mutating
            new_act = dict(act)
            new_act["id"] = str(uuid.uuid4())[:8]
            new_act["start_date"] = part2_start
            new_act.pop("google_event_id", None)

            act["end_date"] = part1_end
            activities.insert(activity_idx + 1, new_act)
    else:
        raise ValueError("Invalid delete_type. Must be 'single' or 'series'")

    matrix["activities"] = activities
    return matrix

