import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List


def parse_date(date_str: str) -> datetime.date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()

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

def apply_disruption(current_matrix: Dict[str, Any], disruption: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a disruption (e.g. cancellation) to the matrix."""
    updated_activities = list(current_matrix.get("activities", []))
    disrupted_child = disruption.get("child_name")
    disruption_date = disruption.get("date")
    
    dis_start = parse_time_to_minutes(disruption.get("start_time", "00:00") or "00:00")
    dis_end = parse_time_to_minutes(disruption.get("end_time", "23:59") or "23:59")
    
    for act in updated_activities:
        if act.get("child_name") == disrupted_child:
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
