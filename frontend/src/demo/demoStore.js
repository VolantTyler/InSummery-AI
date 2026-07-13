import {
    DEMO_MATRIX_KEY,
    DEMO_PROFILE,
    DEMO_SAGE_ACTIVITY,
    DEMO_KAI_PARTIAL,
    DEMO_HITL_QUESTION,
    DEMO_SAMPLE_EMAILS,
    buildSeedActivities,
} from "./demoData.js";

function parseDate(dateStr) {
    const [y, m, d] = dateStr.split("-").map(Number);
    return new Date(y, m - 1, d);
}

function formatDate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function toMinutes(timeStr) {
    const [h, m] = timeStr.split(":").map(Number);
    return h * 60 + m;
}

function fromMinutes(minutes) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function shortId() {
    return `demo-${Math.random().toString(36).slice(2, 10)}`;
}

function cloneMatrix(matrix) {
    return JSON.parse(JSON.stringify(matrix));
}

/** Compact gap calc: absolute leftovers only for kids who have coverage that day. */
export function recalculateGaps(activities, profile = DEMO_PROFILE) {
    const children = (profile.children || []).map((c) => c.name).filter(Boolean);
    const active = (activities || []).filter((a) => a.status === "ACTIVE");
    if (!active.length || !children.length) return [];

    const dates = new Set();
    for (const act of active) {
        const start = parseDate(act.start_date);
        const end = parseDate(act.end_date);
        for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
            if (d.getDay() !== 0 && d.getDay() !== 6) dates.add(formatDate(d));
        }
    }

    const gaps = [];
    const windowStart = 540;
    const windowEnd = 1020;

    for (const dateStr of Array.from(dates).sort()) {
        const coverage = Object.fromEntries(
            children.map((child) => [child, new Array(windowEnd - windowStart).fill(false)])
        );
        const hasActivity = Object.fromEntries(children.map((child) => [child, false]));

        for (const act of active) {
            if (act.start_date > dateStr || dateStr > act.end_date) continue;
            const child = act.child_name;
            if (!coverage[child]) continue;
            hasActivity[child] = true;
            const aStart = toMinutes(act.start_time);
            const aEnd = toMinutes(act.end_time);
            for (let m = windowStart; m < windowEnd; m++) {
                if (aStart <= m && m < aEnd) coverage[child][m - windowStart] = true;
            }
        }

        for (const child of children) {
            if (!hasActivity[child]) continue;
            let inGap = false;
            let gapStart = null;
            for (let idx = 0; idx < coverage[child].length; idx++) {
                const covered = coverage[child][idx];
                const minute = idx + windowStart;
                if (!covered && !inGap) {
                    inGap = true;
                    gapStart = minute;
                } else if (covered && inGap) {
                    inGap = false;
                    gaps.push({
                        child_name: child,
                        date: dateStr,
                        start_time: fromMinutes(gapStart),
                        end_time: fromMinutes(minute),
                        type: "ABSOLUTE",
                        description: `No care scheduled for ${child}.`,
                    });
                }
            }
            if (inGap) {
                gaps.push({
                    child_name: child,
                    date: dateStr,
                    start_time: fromMinutes(gapStart),
                    end_time: fromMinutes(windowEnd),
                    type: "ABSOLUTE",
                    description: `No care scheduled for ${child}.`,
                });
            }
        }
    }

    return gaps;
}

export function buildSeedMatrix() {
    const activities = buildSeedActivities();
    return {
        activities,
        gaps: recalculateGaps(activities),
        warnings: [],
    };
}

/**
 * In-memory guest database for demo mode.
 * localStorage is a persistence mirror only — React always reads from memory
 * so ingestions immediately produce schedule blocks in the UI.
 */
let memoryMatrix = null;
const pendingHitl = new Map();

function ensureMemory() {
    if (memoryMatrix) return memoryMatrix;
    try {
        const raw = localStorage.getItem(DEMO_MATRIX_KEY);
        if (raw) {
            memoryMatrix = JSON.parse(raw);
            return memoryMatrix;
        }
    } catch {
        /* fall through */
    }
    memoryMatrix = buildSeedMatrix();
    persist();
    return memoryMatrix;
}

function persist() {
    if (!memoryMatrix) return;
    localStorage.setItem(DEMO_MATRIX_KEY, JSON.stringify(memoryMatrix));
}

export function loadDemoMatrix() {
    return cloneMatrix(ensureMemory());
}

export function saveDemoMatrix(matrix) {
    memoryMatrix = cloneMatrix(matrix);
    persist();
    return loadDemoMatrix();
}

export function resetDemoMatrix() {
    memoryMatrix = {
        activities: [],
        gaps: [],
        warnings: [],
    };
    persist();
    return loadDemoMatrix();
}

export function restoreSeedDemoMatrix() {
    memoryMatrix = buildSeedMatrix();
    persist();
    return loadDemoMatrix();
}

function normalizeText(text) {
    return (text || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function detectSampleEmail(text) {
    const raw = text || "";
    const normalized = normalizeText(raw);

    // Prefer explicit demo markers embedded in sample emails
    const marker = raw.match(/X-InSummery-Demo:\s*(complete|incomplete)/i);
    if (marker) {
        const id = marker[1].toLowerCase();
        return DEMO_SAMPLE_EMAILS.find((e) => e.id === id) || null;
    }

    if (
        normalized.includes("little explorers day camp") &&
        normalized.includes("sage") &&
        (normalized.includes("july 24") || normalized.includes("august 14"))
    ) {
        return DEMO_SAMPLE_EMAILS.find((e) => e.id === "complete");
    }

    if (
        normalized.includes("youth leadership summit") &&
        normalized.includes("kai") &&
        !normalized.includes("end date:") &&
        !normalized.includes("end time:")
    ) {
        return DEMO_SAMPLE_EMAILS.find((e) => e.id === "incomplete");
    }

    return null;
}

function mergeActivity(activity) {
    const matrix = ensureMemory();
    const activities = [...(matrix.activities || [])];
    const duplicate = activities.some(
        (act) =>
            act.child_name === activity.child_name &&
            act.activity_title === activity.activity_title &&
            act.start_date === activity.start_date &&
            act.end_date === activity.end_date &&
            act.start_time === activity.start_time &&
            act.end_time === activity.end_time
    );

    if (!duplicate) {
        activities.push({
            ...activity,
            id: activity.id || shortId(),
            status: "ACTIVE",
        });
    }

    memoryMatrix = {
        activities,
        gaps: recalculateGaps(activities),
        warnings: matrix.warnings || [],
    };
    persist();
    return loadDemoMatrix();
}

export async function demoProcessEmail(text) {
    await delay(600);
    ensureMemory();
    const sample = detectSampleEmail(text);

    if (sample?.id === "complete") {
        const matrix = mergeActivity(DEMO_SAGE_ACTIVITY);
        return {
            status: "COMPLETED",
            matrix,
            confidence: 92,
            addedActivity: DEMO_SAGE_ACTIVITY,
        };
    }

    if (sample?.id === "incomplete") {
        const workflowId = `demo-hitl-${Date.now()}`;
        pendingHitl.set(workflowId, { kind: "kai-incomplete" });
        return {
            status: "INTERRUPTED",
            workflowId,
            message: DEMO_HITL_QUESTION,
        };
    }

    const workflowId = `demo-hitl-${Date.now()}`;
    pendingHitl.set(workflowId, { kind: "generic", rawText: text });
    return {
        status: "INTERRUPTED",
        workflowId,
        message:
            "I couldn't confidently extract a full schedule from that text. Please reply with the child name, activity title, start/end dates, and start/end times (e.g. \"Sage, Art Camp, 2026-07-20 to 2026-07-24, 9:00–12:00\").",
    };
}

export async function demoResumeWorkflow(workflowId, responseText) {
    await delay(450);
    ensureMemory();
    const pending = pendingHitl.get(workflowId);
    pendingHitl.delete(workflowId);

    if (!pending) {
        throw new Error("Demo workflow not found. Try processing the email again.");
    }

    if (pending.kind === "kai-incomplete") {
        const parsed = parseHitlEndDetails(responseText);
        const activity = {
            ...DEMO_KAI_PARTIAL,
            end_date: parsed.end_date,
            end_time: parsed.end_time,
            notes: `${DEMO_KAI_PARTIAL.notes} Confirmed end: ${parsed.end_date} ${parsed.end_time}.`,
        };
        const matrix = mergeActivity(activity);
        return { status: "COMPLETED", matrix, addedActivity: activity };
    }

    const parsed = parseGenericScheduleReply(responseText);
    if (!parsed) {
        const retryId = `demo-hitl-${Date.now()}`;
        pendingHitl.set(retryId, pending);
        return {
            status: "INTERRUPTED",
            workflowId: retryId,
            message:
                "Still missing details. Please include child, activity, dates (YYYY-MM-DD or Mon DD), and times (e.g. 9:00–12:00).",
        };
    }
    const matrix = mergeActivity(parsed);
    return { status: "COMPLETED", matrix, addedActivity: parsed };
}

export function demoDeleteActivity({ activity_id, delete_type, date }) {
    const matrix = ensureMemory();
    let activities = [...(matrix.activities || [])];
    const target = activities.find((a) => a.id === activity_id);
    if (!target) {
        throw new Error("Activity not found");
    }

    if (delete_type === "series" || !date) {
        activities = activities.filter((a) => a.id !== activity_id);
    } else if (delete_type === "single") {
        activities = activities.filter((a) => a.id !== activity_id);
        const start = parseDate(target.start_date);
        const end = parseDate(target.end_date);
        const day = parseDate(date);
        if (start < day) {
            const beforeEnd = new Date(day);
            beforeEnd.setDate(beforeEnd.getDate() - 1);
            activities.push({
                ...target,
                id: shortId(),
                end_date: formatDate(beforeEnd),
            });
        }
        if (day < end) {
            const afterStart = new Date(day);
            afterStart.setDate(afterStart.getDate() + 1);
            activities.push({
                ...target,
                id: shortId(),
                start_date: formatDate(afterStart),
            });
        }
    }

    memoryMatrix = {
        activities,
        gaps: recalculateGaps(activities),
        warnings: matrix.warnings || [],
    };
    persist();
    return loadDemoMatrix();
}

function parseHitlEndDetails(text) {
    const lower = text.toLowerCase();
    let end_date = "2026-07-24";
    let end_time = "17:00";

    const iso = text.match(/(\d{4}-\d{2}-\d{2})/);
    if (iso) end_date = iso[1];

    const julyDay = lower.match(/jul(?:y)?\s+(\d{1,2})(?:,?\s*2026)?/);
    if (julyDay) {
        end_date = `2026-07-${String(Number(julyDay[1])).padStart(2, "0")}`;
    }

    const augDay = lower.match(/aug(?:ust)?\s+(\d{1,2})(?:,?\s*2026)?/);
    if (augDay) {
        end_date = `2026-08-${String(Number(augDay[1])).padStart(2, "0")}`;
    }

    const timeMatch = text.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
    if (timeMatch) {
        let h = Number(timeMatch[1]);
        const m = timeMatch[2] ? Number(timeMatch[2]) : 0;
        const ampm = (timeMatch[3] || "").toLowerCase();
        if (ampm === "pm" && h < 12) h += 12;
        if (ampm === "am" && h === 12) h = 0;
        if (!ampm && h >= 1 && h <= 7) h += 12;
        end_time = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    }

    if (lower.includes("5") && (lower.includes("pm") || lower.includes("17"))) {
        end_time = "17:00";
    }

    return { end_date, end_time };
}

function parseGenericScheduleReply(text) {
    const isoDates = [...text.matchAll(/(\d{4}-\d{2}-\d{2})/g)].map((m) => m[1]);
    const times = [...text.matchAll(/(\d{1,2}:\d{2})/g)].map((m) => m[1]);
    const child = DEMO_PROFILE.children.find((c) =>
        text.toLowerCase().includes(c.name.toLowerCase())
    );
    if (!child || isoDates.length < 1) return null;

    const start_date = isoDates[0];
    const end_date = isoDates[1] || isoDates[0];
    const start_time = times[0] || "09:00";
    const end_time = times[1] || "12:00";
    const titleMatch = text.match(/,\s*([^,]+?),\s*(?:jul|aug|\d{4})/i);
    return {
        child_name: child.name,
        activity_title: titleMatch ? titleMatch[1].trim() : "Demo Activity",
        start_date,
        end_date,
        start_time,
        end_time,
        location: "",
        notes: "Added from demo clarification reply.",
    };
}

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
