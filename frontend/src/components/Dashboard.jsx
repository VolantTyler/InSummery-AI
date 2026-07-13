import { useState, useEffect, useRef } from "react";
import { auth, authSignOut, DIRECT_API_URL } from "../firebase.js";
import { apiFetch } from "../api.js";
import BrandLogo from "./BrandLogo.jsx";
import MatrixGrid from "./MatrixGrid.jsx";
import AlertsSidebar from "./AlertsSidebar.jsx";
import HitlModal from "./HitlModal.jsx";
import ProfileModal from "./ProfileModal.jsx";
import DeleteActivityModal from "./DeleteActivityModal.jsx";
import { DEMO_SAMPLE_EMAILS, DEMO_STORAGE_KEY } from "../demo/demoData.js";
import {
    demoProcessEmail,
    demoResumeWorkflow,
    demoDeleteActivity,
    resetDemoMatrix,
    restoreSeedDemoMatrix,
} from "../demo/demoStore.js";

function scrollToDayCard(dateStr) {
    if (!dateStr) return;
    requestAnimationFrame(() => {
        const el = document.getElementById(`day-${dateStr}`);
        if (el) {
            el.classList.add("day-card-highlight");
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            setTimeout(() => el.classList.remove("day-card-highlight"), 2400);
        }
    });
}

function isGuestDemo() {
    return localStorage.getItem(DEMO_STORAGE_KEY) === "1";
}

export default function Dashboard({
    user,
    token,
    profile,
    matrix,
    loadError,
    onReload,
    theme,
    onToggleTheme,
    demoMode = false,
    onExitDemo,
    onMatrixChange,
}) {
    const [ingestText, setIngestText] = useState("");
    const [isDisruption, setIsDisruption] = useState(false);
    const [ingestStatus, setIngestStatus] = useState(null); // { msg, type }
    const [submitting, setSubmitting] = useState(false);
    const [hitl, setHitl] = useState(null); // { workflowId, question }
    const [profileOpen, setProfileOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [selectedActivity, setSelectedActivity] = useState(null); // { id, date, title, start_date, end_date }
    const [copiedEmailId, setCopiedEmailId] = useState(null);
    const [pasteNotice, setPasteNotice] = useState(false);
    const ingestTextareaRef = useRef(null);
    const pasteNoticeTimer = useRef(null);

    const handleActivityClick = (id, date, title, start_date, end_date) => {
        setSelectedActivity({ id, date, title, start_date, end_date });
    };

    const applyDemoMatrix = (res) => {
        if (!res?.matrix) return;
        onMatrixChange?.(res.matrix);
        const focusDate = res.addedActivity?.start_date;
        if (focusDate) {
            // Wait for React to paint the new day cards before scrolling.
            setTimeout(() => scrollToDayCard(focusDate), 120);
        }
    };

    const handleDeleteActivity = async (deleteType) => {
        if (!selectedActivity) return;
        showStatus("Deleting activity...", "loading");
        const actId = selectedActivity.id;
        const actDate = selectedActivity.date;
        setSelectedActivity(null);

        try {
            if (demoMode) {
                const next = demoDeleteActivity({
                    activity_id: actId,
                    delete_type: deleteType,
                    date: actDate,
                });
                onMatrixChange?.(next);
                showStatus("Activity deleted successfully!", "success");
                return;
            }

            await apiFetch(token, "delete-activity", {
                method: "POST",
                body: JSON.stringify({
                    activity_id: actId,
                    delete_type: deleteType,
                    date: actDate,
                }),
                baseUrl: DIRECT_API_URL,
            });
            showStatus("Activity deleted successfully!", "success");
            onReload();
        } catch (err) {
            showStatus(`Error deleting activity: ${err.message}`, "error");
        }
    };

    useEffect(() => {
        if (!menuOpen) return;
        const handleOutsideClick = (e) => {
            if (!e.target.closest(".mobile-menu-container")) {
                setMenuOpen(false);
            }
        };
        document.addEventListener("click", handleOutsideClick);
        return () => document.removeEventListener("click", handleOutsideClick);
    }, [menuOpen]);

    useEffect(() => () => {
        if (pasteNoticeTimer.current) clearTimeout(pasteNoticeTimer.current);
    }, []);

    const showStatus = (msg, type) => setIngestStatus({ msg, type });
    const inDemo = demoMode || isGuestDemo();

    const handleIngest = async () => {
        const text = ingestText.trim();
        if (!text) return;

        showStatus("Processing text with AI...", "loading");
        setSubmitting(true);
        setPasteNotice(false);

        try {
            if (inDemo) {
                const res = await demoProcessEmail(text);
                if (res.status === "INTERRUPTED") {
                    showStatus("Clarification required...", "loading");
                    setHitl({ workflowId: res.workflowId, question: res.message });
                } else {
                    applyDemoMatrix(res);
                    const title = res.addedActivity?.activity_title;
                    const child = res.addedActivity?.child_name;
                    showStatus(
                        child && title
                            ? `Added ${title} for ${child} to the schedule.`
                            : "Schedule updated successfully!",
                        "success"
                    );
                    setIngestText("");
                }
            } else {
                const res = await apiFetch(token, "process-email", {
                    method: "POST",
                    body: JSON.stringify({ text, isDisruption }),
                    baseUrl: DIRECT_API_URL,
                });

                if (res.status === "INTERRUPTED") {
                    showStatus("Clarification required...", "loading");
                    setHitl({ workflowId: res.workflowId, question: res.message });
                } else {
                    showStatus("Schedule updated successfully!", "success");
                    setIngestText("");
                    onReload();
                }
            }
        } catch (err) {
            showStatus(`Error: ${err.message}`, "error");
        } finally {
            setSubmitting(false);
        }
    };

    const handleHitlSubmit = async (responseText) => {
        const workflowId = hitl.workflowId;
        setHitl(null);
        showStatus("Resuming AI analysis...", "loading");

        try {
            if (inDemo) {
                const res = await demoResumeWorkflow(workflowId, responseText);
                if (res.status === "INTERRUPTED") {
                    setHitl({ workflowId: res.workflowId, question: res.message });
                } else {
                    applyDemoMatrix(res);
                    const title = res.addedActivity?.activity_title;
                    const child = res.addedActivity?.child_name;
                    showStatus(
                        child && title
                            ? `Added ${title} for ${child} to the schedule.`
                            : "Schedule updated successfully!",
                        "success"
                    );
                    setIngestText("");
                }
                return;
            }

            const res = await apiFetch(token, "resume-workflow", {
                method: "POST",
                body: JSON.stringify({ workflowId, response: responseText }),
                baseUrl: DIRECT_API_URL,
            });

            if (res.status === "INTERRUPTED") {
                setHitl({ workflowId: res.workflowId, question: res.message });
            } else {
                showStatus("Schedule updated successfully!", "success");
                setIngestText("");
                onReload();
            }
        } catch (err) {
            showStatus(`Error: ${err.message}`, "error");
        }
    };

    const handleConnectCalendar = async () => {
        showStatus("Connecting Google Calendar...", "loading");
        try {
            const res = await apiFetch(token, "oauth/google-calendar/start");
            if (res.url) {
                window.location.href = res.url;
            } else {
                showStatus("Failed to retrieve Google Authorization URL.", "error");
            }
        } catch (err) {
            showStatus(`Connection failed: ${err.message}`, "error");
        }
    };

    const handleSyncCalendar = async () => {
        showStatus("Syncing with Google Calendar...", "loading");
        try {
            const res = await apiFetch(token, "sync-calendar", {
                method: "POST",
            });
            if (res.status === "SUCCESS") {
                showStatus("Google Calendar synced successfully!", "success");
            } else {
                showStatus(`Sync failed: ${res.error || "Unknown error"}`, "error");
            }
        } catch (err) {
            showStatus(`Sync failed: ${err.message}`, "error");
        }
    };

    const handleCopySampleEmail = async (email) => {
        setIngestText(email.text);
        setPasteNotice(true);
        setCopiedEmailId(email.id);
        if (pasteNoticeTimer.current) clearTimeout(pasteNoticeTimer.current);
        pasteNoticeTimer.current = setTimeout(() => {
            setPasteNotice(false);
            setCopiedEmailId(null);
        }, 4000);

        try {
            await navigator.clipboard.writeText(email.text);
        } catch {
            /* paste into the textarea still works via setIngestText */
        }

        requestAnimationFrame(() => {
            const el = ingestTextareaRef.current;
            if (!el) return;
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            el.focus();
        });
    };

    const handleResetSchedules = () => {
        if (!demoMode) return;
        const empty = resetDemoMatrix();
        onMatrixChange?.(empty);
        setIngestText("");
        setHitl(null);
        setPasteNotice(false);
        showStatus("All schedules cleared. Paste a registration email to rebuild.", "success");
    };

    const handleRestoreSeed = () => {
        if (!demoMode) return;
        const seed = restoreSeedDemoMatrix();
        onMatrixChange?.(seed);
        setIngestText("");
        setHitl(null);
        setPasteNotice(false);
        showStatus("Demo schedules restored for Remy and Quinn.", "success");
    };

    const calendarConnected = profile?.google_calendar_connected === true;

    return (
        <div id="dashboard-view" className="view">
            <header>
                <div className="header-brand">
                    <BrandLogo size={36} textClassName="header-brand-title" />
                    <span className={`badge ${demoMode ? "badge-demo" : ""}`}>
                        {demoMode ? "Demo Mode" : "Concierge Active"}
                    </span>
                </div>
                <div className="header-actions desktop-nav">
                    {!demoMode && (
                        <button className="btn btn-sm btn-outline" onClick={() => setProfileOpen(true)}>
                            Family Profile
                        </button>
                    )}
                    {demoMode ? (
                        <>
                            <button className="btn btn-sm btn-outline" onClick={handleRestoreSeed}>
                                Restore demo schedules
                            </button>
                            <button className="btn btn-sm btn-outline btn-danger-outline" onClick={handleResetSchedules}>
                                Reset all schedules
                            </button>
                        </>
                    ) : calendarConnected ? (
                        <button className="btn btn-sm btn-outline" onClick={handleSyncCalendar}>
                            Sync Calendar
                        </button>
                    ) : (
                        <button className="btn btn-sm btn-outline" onClick={handleConnectCalendar}>
                            Connect Google Calendar
                        </button>
                    )}
                    <button className="theme-toggle" onClick={onToggleTheme}>
                        {theme === "dark" ? "Light Mode" : "Dark Mode"}
                    </button>
                    <div className="user-profile">
                        <span>{user ? (user.displayName || user.email) : "Sign In"}</span>
                        {demoMode ? (
                            <button className="btn btn-sm btn-outline" onClick={onExitDemo}>
                                Exit Demo
                            </button>
                        ) : (
                            user && (
                                <button className="btn btn-sm btn-outline" onClick={() => authSignOut(auth)}>
                                    Sign Out
                                </button>
                            )
                        )}
                    </div>
                </div>

                <div className="mobile-menu-container">
                    <button className="mobile-menu-toggle" onClick={() => setMenuOpen(!menuOpen)}>
                        <span>{user ? (user.displayName || user.email) : "Sign In"}</span>
                        <svg className={`chevron-icon ${menuOpen ? "open" : ""}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                    {menuOpen && (
                        <div className="mobile-dropdown-menu">
                            {!demoMode && (
                                <button className="dropdown-item" onClick={() => { setProfileOpen(true); setMenuOpen(false); }}>
                                    Family Profile
                                </button>
                            )}
                            {demoMode ? (
                                <>
                                    <button className="dropdown-item" onClick={() => { handleRestoreSeed(); setMenuOpen(false); }}>
                                        Restore demo schedules
                                    </button>
                                    <button className="dropdown-item" onClick={() => { handleResetSchedules(); setMenuOpen(false); }}>
                                        Reset all schedules
                                    </button>
                                    <button className="dropdown-item logout-item" onClick={() => { onExitDemo?.(); setMenuOpen(false); }}>
                                        Exit Demo
                                    </button>
                                </>
                            ) : calendarConnected ? (
                                <button className="dropdown-item" onClick={() => { handleSyncCalendar(); setMenuOpen(false); }}>
                                    Sync Calendar
                                </button>
                            ) : (
                                <button className="dropdown-item" onClick={() => { handleConnectCalendar(); setMenuOpen(false); }}>
                                    Connect Google Calendar
                                </button>
                            )}
                            <button className="dropdown-item" onClick={() => { onToggleTheme(); setMenuOpen(false); }}>
                                {theme === "dark" ? "Light Mode" : "Dark Mode"}
                            </button>
                            {!demoMode && user && (
                                <button className="dropdown-item logout-item" onClick={() => { authSignOut(auth); setMenuOpen(false); }}>
                                    Sign Out
                                </button>
                            )}
                        </div>
                    )}
                </div>
            </header>

            <div className="main-container">
                <aside className="sidebar">
                    <div className="sidebar-card">
                        <h3>Ingest Schedule</h3>
                        <p className="section-desc">Paste an email, registration confirmation, or disruption notice.</p>
                        <textarea
                            ref={ingestTextareaRef}
                            placeholder="e.g., Emily is registered for Soccer Camp from July 6 to July 10, daily 9:00 to 12:00..."
                            value={ingestText}
                            onChange={(e) => {
                                setIngestText(e.target.value);
                                if (pasteNotice) setPasteNotice(false);
                            }}
                        />
                        {pasteNotice && <div className="paste-notice">Text pasted</div>}

                        <div className="ingest-options">
                            <label className="checkbox-label">
                                <input
                                    type="checkbox"
                                    checked={isDisruption}
                                    onChange={(e) => setIsDisruption(e.target.checked)}
                                    disabled={demoMode}
                                />
                                <span>This is a schedule disruption</span>
                            </label>
                        </div>

                        <button className="btn btn-primary btn-block" onClick={handleIngest} disabled={submitting}>
                            Process with AI
                        </button>
                        {ingestStatus && (
                            <div className={`status-indicator status-${ingestStatus.type}`}>
                                {ingestStatus.msg}
                            </div>
                        )}
                    </div>

                    {demoMode && (
                        <div className="sidebar-card demo-samples-card">
                            <h3>Sample registration emails</h3>
                            <p className="section-desc">
                                Copy into the ingest box to try high-confidence parsing or the parent confirmation flow.
                            </p>
                            <div className="demo-sample-list">
                                {DEMO_SAMPLE_EMAILS.map((email) => (
                                    <div className="demo-sample-item" key={email.id}>
                                        <div className="demo-sample-meta">
                                            <strong>{email.label}</strong>
                                            <span>{email.description}</span>
                                        </div>
                                        <button
                                            type="button"
                                            className="btn btn-sm btn-outline"
                                            onClick={() => handleCopySampleEmail(email)}
                                        >
                                            {copiedEmailId === email.id ? "Copied" : "Copy & paste"}
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    <AlertsSidebar matrix={matrix} />
                </aside>

                <main className="content-area">
                    <div className="matrix-header">
                        <h2>Schedule Matrix</h2>
                        <div className="matrix-legend">
                            <span className="legend-item"><span className="color-box status-school"></span> School</span>
                            <span className="legend-item"><span className="color-box status-active"></span> Active</span>
                            <span className="legend-item"><span className="color-box status-disrupted"></span> Disrupted</span>
                            <span className="legend-item"><span className="color-box status-gap"></span> Gap</span>
                        </div>
                    </div>

                    {demoMode && (
                        <p className="demo-matrix-hint">
                            Preloaded family: Jordan Okonkwo &amp; Avery Chen with Remy, Quinn, Sage, and Kai.
                            Remy and Quinn have camps across four weeks in July–August; Sage and Kai are ready for the sample emails.
                        </p>
                    )}

                    <div className="matrix-grid">
                        {loadError ? (
                            <div className="loading-placeholder" style={{ color: "var(--danger-text)" }}>
                                Error loading schedule: {loadError}
                            </div>
                        ) : matrix && profile ? (
                            <MatrixGrid matrix={matrix} profile={profile} onActivityClick={handleActivityClick} />
                        ) : (
                            <div className="loading-placeholder">Loading schedule matrix...</div>
                        )}
                    </div>
                </main>
            </div>

            {profileOpen && !demoMode && (
                <ProfileModal
                    token={token}
                    onClose={() => setProfileOpen(false)}
                    onSaved={() => {
                        setProfileOpen(false);
                        onReload();
                    }}
                />
            )}

            {hitl && <HitlModal question={hitl.question} onSubmit={handleHitlSubmit} />}

            {selectedActivity && (
                <DeleteActivityModal
                    activity={selectedActivity}
                    onDelete={handleDeleteActivity}
                    onClose={() => setSelectedActivity(null)}
                />
            )}
        </div>
    );
}
