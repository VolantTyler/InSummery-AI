// Renders the day-by-day schedule matrix: children on one axis, weekdays as cards.

function isDateInBaseline(date, baseline) {
    if (baseline.start_date) {
        const start = new Date(baseline.start_date + "T00:00:00");
        if (date < start) return false;
    }

    if (baseline.end_date) {
        const end = new Date(baseline.end_date + "T00:00:00");
        if (date > end) return false;
    }

    const monthName = date.toLocaleDateString("en-US", { month: "long" });
    if (!baseline.start_date && !baseline.end_date && baseline.months?.length && !baseline.months.includes(monthName)) {
        return false;
    }

    const configuredDays = baseline.days || baseline.days_of_week || [1, 2, 3, 4, 5];
    const dayName = date.toLocaleDateString("en-US", { weekday: "long" });
    const jsDay = date.getDay();

    return configuredDays.some(day => {
        if (typeof day === "string") {
            return day.toLowerCase() === dayName.toLowerCase() || Number(day) === jsDay;
        }
        return day === jsDay;
    });
}

function buildTimelineItems(child, dateStr, dateObj, activities, gaps, baselines) {
    const items = [];

    // 1. School baseline coverage
    baselines.forEach(baseline => {
        if (isDateInBaseline(dateObj, baseline)) {
            items.push({
                start_time: baseline.start_time,
                end_time: baseline.end_time,
                title: baseline.name,
                className: "status-school",
                notes: "Baseline school hours"
            });
        }
    });

    // 2. Activities
    activities.forEach(act => {
        if (act.child_name === child && act.start_date <= dateStr && dateStr <= act.end_date) {
            items.push({
                start_time: act.start_time,
                end_time: act.end_time,
                title: act.activity_title,
                className: act.status === "ACTIVE" ? "status-active" : "status-disrupted",
                notes: act.notes || ""
            });
        }
    });

    // 3. Gaps
    gaps.forEach(gap => {
        if (gap.child_name === child && gap.date === dateStr) {
            items.push({
                start_time: gap.start_time,
                end_time: gap.end_time,
                title: gap.type === "ABSOLUTE" ? "Childcare Gap" : "Sibling Care Mismatch",
                className: "status-gap",
                notes: gap.description || ""
            });
        }
    });

    items.sort((a, b) => a.start_time.localeCompare(b.start_time));
    return items;
}

export default function MatrixGrid({ matrix, profile }) {
    const activities = matrix.activities || [];
    const gaps = matrix.gaps || [];

    const datesSet = new Set();
    activities.forEach(act => {
        datesSet.add(act.start_date);
        datesSet.add(act.end_date);
    });
    gaps.forEach(gap => datesSet.add(gap.date));

    if (datesSet.size === 0) {
        return <div className="loading-placeholder">No scheduled activities found. Paste an email to get started!</div>;
    }

    const sortedDates = Array.from(datesSet).sort();
    const children = (profile.children || []).map(c => c.name).filter(Boolean);
    const baselines = profile.baseline_coverage || [];

    return (
        <>
            {sortedDates.map(dateStr => {
                const dateObj = new Date(dateStr + "T00:00:00");
                const dayOfWeek = dateObj.getDay();
                if (dayOfWeek === 0 || dayOfWeek === 6) return null; // Weekdays only

                const dayName = dateObj.toLocaleDateString("en-US", {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                    year: "numeric"
                });

                return (
                    <div className="day-card" key={dateStr}>
                        <div className="day-header">{dayName}</div>
                        <div className="children-columns">
                            {children.map(child => {
                                const items = buildTimelineItems(child, dateStr, dateObj, activities, gaps, baselines);
                                return (
                                    <div className="child-column" key={child}>
                                        <div className="child-name">{child}</div>
                                        {items.length > 0 ? (
                                            items.map((item, idx) => (
                                                <div className={`timeline-item ${item.className}`} key={idx}>
                                                    <div className="item-time">{item.start_time} - {item.end_time}</div>
                                                    <div className="item-title">{item.title}</div>
                                                    {item.notes && <div className="item-notes">{item.notes}</div>}
                                                </div>
                                            ))
                                        ) : (
                                            <div className="no-alerts" style={{ padding: "20px 0" }}>No activities</div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                );
            })}
        </>
    );
}
