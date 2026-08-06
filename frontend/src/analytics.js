/**
 * Product analytics (GA4) + Core Web Vitals reporting.
 *
 * Weave stays server-side: the browser only POSTs numeric page-load metrics
 * to /client-metrics, which the Cloud Function records as Weave ops when
 * WANDB_API_KEY is configured. Never put WANDB_API_KEY in VITE_* env vars.
 */

// Resolve API base without importing firebase.js so analytics can load
// without pulling the Auth SDK onto the critical path.
const API_URL =
    import.meta.env.VITE_API_URL || "http://127.0.0.1:5001/insummery-ai/us-central1/api";

const GA_ID = import.meta.env.VITE_GA_MEASUREMENT_ID || "";
const METRICS_ENABLED =
    (import.meta.env.VITE_CLIENT_METRICS_ENABLED || "true").toLowerCase() !== "false";

let gaReady = false;
let sessionId = null;
let vitalsHooked = false;
let navigationReported = false;

function getSessionId() {
    if (sessionId) return sessionId;
    try {
        sessionId = sessionStorage.getItem("insummery_analytics_sid");
        if (!sessionId) {
            sessionId = `s_${Math.random().toString(36).slice(2, 10)}_${Date.now().toString(36)}`;
            sessionStorage.setItem("insummery_analytics_sid", sessionId);
        }
    } catch {
        sessionId = `s_${Date.now().toString(36)}`;
    }
    return sessionId;
}

/** Load gtag.js when a measurement ID is configured. Safe no-op otherwise. */
export function initAnalytics() {
    if (!GA_ID || typeof window === "undefined") return;
    if (window.gtag) {
        gaReady = true;
        return;
    }

    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() {
        window.dataLayer.push(arguments);
    };
    window.gtag("js", new Date());
    window.gtag("config", GA_ID, {
        send_page_view: false,
        anonymize_ip: true,
    });

    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_ID)}`;
    document.head.appendChild(script);
    gaReady = true;
}

export function trackPageView(view) {
    if (!gaReady || !window.gtag || !view) return;
    window.gtag("event", "page_view", {
        page_title: view,
        page_path: `/${view}`,
        page_location: `${window.location.origin}/${view}`,
    });
}

export function trackEvent(name, params = {}) {
    if (!gaReady || !window.gtag || !name) return;
    window.gtag("event", name, params);
}

function clampMetric(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
    if (value < 0) return undefined;
    // Cap absurd outliers (ms or unitless CLS scaled later).
    return Math.min(value, 600_000);
}

function collectNavigationMetrics() {
    const metrics = {};
    try {
        const nav = performance.getEntriesByType("navigation")[0];
        if (nav) {
            metrics.ttfb = clampMetric(nav.responseStart);
            metrics.dom_content_loaded = clampMetric(nav.domContentLoadedEventEnd);
            metrics.load_event = clampMetric(nav.loadEventEnd);
        }
        const paints = performance.getEntriesByType("paint");
        for (const paint of paints) {
            if (paint.name === "first-paint") {
                metrics.time_to_paint = clampMetric(paint.startTime);
            }
            if (paint.name === "first-contentful-paint") {
                metrics.fcp = clampMetric(paint.startTime);
            }
        }
    } catch {
        // Performance Timeline may be unavailable in some test environments.
    }
    return metrics;
}

function postClientMetrics(payload) {
    if (!METRICS_ENABLED) return;
    const body = JSON.stringify(payload);
    const url = `${API_URL.replace(/\/$/, "")}/client-metrics`;
    try {
        if (navigator.sendBeacon) {
            const blob = new Blob([body], { type: "application/json" });
            if (navigator.sendBeacon(url, blob)) return;
        }
    } catch {
        // fall through to fetch
    }
    fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
        mode: "cors",
    }).catch(() => {
        // Best-effort; never block UX on analytics.
    });
}

/**
 * Report Core Web Vitals + navigation paint timings to GA and Weave (via API).
 * @param {string} view - current app shell view
 */
export async function reportWebVitals(view = "boot") {
    const activeView = String(view || "boot").slice(0, 32);
    const base = {
        view: activeView,
        path: window.location.pathname.slice(0, 128),
        session_id: getSessionId(),
        ...collectNavigationMetrics(),
    };

    // Navigation/paint snapshot once per full page load.
    if (!navigationReported) {
        navigationReported = true;
        postClientMetrics({ ...base, source: "navigation" });
        if (base.fcp != null) {
            trackEvent("web_vital", {
                metric_name: "FCP",
                value: Math.round(base.fcp),
                view: activeView,
            });
        }
        if (base.time_to_paint != null) {
            trackEvent("web_vital", {
                metric_name: "TTP",
                value: Math.round(base.time_to_paint),
                view: activeView,
            });
        }
    }

    if (vitalsHooked) return;
    vitalsHooked = true;

    try {
        const { onCLS, onINP, onLCP, onTTFB, onFCP } = await import("web-vitals");
        const send = (metric) => {
            const name = metric.name.toLowerCase();
            const value =
                name === "cls"
                    ? Math.round(metric.value * 1000) / 1000
                    : Math.round(metric.value);
            trackEvent("web_vital", {
                metric_name: metric.name,
                value,
                rating: metric.rating,
                view: activeView,
            });
            postClientMetrics({
                view: activeView,
                path: base.path,
                session_id: base.session_id,
                source: "web-vitals",
                [name]: name === "cls" ? value : clampMetric(metric.value),
                rating: metric.rating,
            });
        };
        onCLS(send);
        onINP(send);
        onLCP(send);
        onTTFB(send);
        onFCP(send);
    } catch {
        vitalsHooked = false;
    }
}
