import { useState } from "react";
import { formatTimeRange12h } from "../timeUtils.js";

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

function eachDateInclusive(startStr, endStr, sink) {
    const start = new Date(startStr + "T00:00:00");
    const end = new Date(endStr + "T00:00:00");
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        sink.add(`${y}-${m}-${day}`);
    }
}

function buildTimelineItems(child, dateStr, dateObj, activities, gaps, baselines) {
    const items = [];

    baselines.forEach(baseline => {
        if (isDateInBaseline(dateObj, baseline)) {
            items.push({
                start_time: baseline.start_time,
                end_time: baseline.end_time,
                title: baseline.name,
                className: "status-school",
                notes: "Baseline school hours",
                location: "",
                details: ["Baseline school hours"],
            });
        }
    });

    activities.forEach(act => {
        if (act.child_name === child && act.start_date <= dateStr && dateStr <= act.end_date) {
            const details = [];
            if (act.location) details.push(act.location);
            if (act.notes) details.push(act.notes);
            items.push({
                id: act.id,
                start_date: act.start_date,
                end_date: act.end_date,
                start_time: act.start_time,
                end_time: act.end_time,
                title: act.activity_title,
                className: act.status === "ACTIVE" ? "status-active" : "status-disrupted",
                notes: act.notes || "",
                location: act.location || "",
                details,
                type: "activity",
            });
        }
    });

    gaps.forEach(gap => {
        if (gap.child_name === child && gap.date === dateStr) {
            const details = gap.description ? [gap.description] : [];
            items.push({
                start_time: gap.start_time,
                end_time: gap.end_time,
                title: gap.type === "ABSOLUTE" ? "Childcare Gap" : "Sibling Care Mismatch",
                className: "status-gap",
                notes: gap.description || "",
                location: "",
                details,
            });
        }
    });

    items.sort((a, b) => a.start_time.localeCompare(b.start_time));
    return items;
}

function TimelineCard({ item, dateStr, onActivityClick }) {
    const [expanded, setExpanded] = useState(false);
    const isActivity = item.type === "activity";
    const hasDetails = Array.isArray(item.details) && item.details.length > 0;

    const handleCardClick = () => {
        if (isActivity && onActivityClick) {
            onActivityClick(item.id, dateStr, item.title, item.start_date, item.end_date);
        }
    };

    const handleToggleDetails = (e) => {
        e.stopPropagation();
        setExpanded((v) => !v);
    };

    return (
        <div
            className={`timeline-item ${item.className} ${isActivity ? "interactive-activity" : ""}`}
            onClick={handleCardClick}
        >
            <div className="item-header-row">
                <div className="item-header-text">
                    <div className="item-time">{formatTimeRange12h(item.start_time, item.end_time)}</div>
                    <div className="item-title">{item.title}</div>
                </div>
                {hasDetails && (
                    <button
                        type="button"
                        className={`item-details-toggle ${expanded ? "expanded" : ""}`}
                        title="View details"
                        aria-label="View details"
                        aria-expanded={expanded}
                        onClick={handleToggleDetails}
                    >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                )}
            </div>
            {hasDetails && expanded && (
                <div className="item-details">
                    {item.location && <div className="item-detail-line">{item.location}</div>}
                    {item.notes && <div className="item-detail-line item-notes">{item.notes}</div>}
                    {!item.location && !item.notes && item.details.map((line, i) => (
                        <div className="item-detail-line" key={i}>{line}</div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function MatrixGrid({ matrix, profile, onActivityClick }) {
    const activities = matrix.activities || [];
    const gaps = matrix.gaps || [];

    const datesSet = new Set();
    activities.forEach(act => {
        eachDateInclusive(act.start_date, act.end_date, datesSet);
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
                    <div className="day-card" key={dateStr} id={`day-${dateStr}`}>
                        <div className="day-header">{dayName}</div>
                        <div className="children-columns">
                            {children.map(child => {
                                const items = buildTimelineItems(child, dateStr, dateObj, activities, gaps, baselines);
                                return (
                                    <div className="child-column" key={child}>
                                        <div className="child-name">{child}</div>
                                        {items.length > 0 ? (
                                            items.map((item, idx) => (
                                                <TimelineCard
                                                    key={`${child}-${dateStr}-${idx}`}
                                                    item={item}
                                                    dateStr={dateStr}
                                                    onActivityClick={onActivityClick}
                                                />
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
