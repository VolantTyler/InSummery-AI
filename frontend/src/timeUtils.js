/** Convert a 24-hour HH:MM string to 12-hour display (e.g. "08:30" → "8:30 AM"). */
export function formatTime12h(timeStr) {
    if (!timeStr) return timeStr;
    const [hStr, mStr = "00"] = timeStr.split(":");
    let h = parseInt(hStr, 10);
    const period = h >= 12 ? "PM" : "AM";
    if (h === 0) h = 12;
    else if (h > 12) h -= 12;
    return `${h}:${mStr} ${period}`;
}

/** Format a start/end time range in 12-hour display. */
export function formatTimeRange12h(start, end) {
    return `${formatTime12h(start)} - ${formatTime12h(end)}`;
}
