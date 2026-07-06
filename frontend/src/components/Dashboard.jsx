import { useState, useEffect } from "react";
import { auth, authSignOut } from "../firebase.js";
import { apiFetch } from "../api.js";
import BrandLogo from "./BrandLogo.jsx";
import MatrixGrid from "./MatrixGrid.jsx";
import AlertsSidebar from "./AlertsSidebar.jsx";
import HitlModal from "./HitlModal.jsx";
import ProfileModal from "./ProfileModal.jsx";

export default function Dashboard({ user, token, profile, matrix, loadError, onReload, theme, onToggleTheme }) {
    const [ingestText, setIngestText] = useState("");
    const [isDisruption, setIsDisruption] = useState(false);
    const [ingestStatus, setIngestStatus] = useState(null); // { msg, type }
    const [submitting, setSubmitting] = useState(false);
    const [hitl, setHitl] = useState(null); // { workflowId, question }
    const [profileOpen, setProfileOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);

    // Close mobile dropdown when clicking outside
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

    const showStatus = (msg, type) => setIngestStatus({ msg, type });

    const handleIngest = async () => {
        const text = ingestText.trim();
        if (!text) return;

        showStatus("Processing text with AI...", "loading");
        setSubmitting(true);

        try {
            const res = await apiFetch(token, "process-email", {
                method: "POST",
                body: JSON.stringify({ text, isDisruption })
            });

            if (res.status === "INTERRUPTED") {
                showStatus("Clarification required...", "loading");
                setHitl({ workflowId: res.workflowId, question: res.message });
            } else {
                showStatus("Schedule updated successfully!", "success");
                setIngestText("");
                onReload();
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
            const res = await apiFetch(token, "resume-workflow", {
                method: "POST",
                body: JSON.stringify({ workflowId, response: responseText })
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
                method: "POST"
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


    return (
        <div id="dashboard-view" className="view">
            <header>
                <div className="header-brand">
                    <BrandLogo size={36} textClassName="header-brand-title" />
                    <span className="badge">Concierge Active</span>
                </div>
                {/* Desktop Nav Actions */}
                <div className="header-actions desktop-nav">
                    <button className="btn btn-sm btn-outline" onClick={() => setProfileOpen(true)}>
                        Family Profile
                    </button>
                    <button className="btn btn-sm btn-outline" onClick={handleConnectCalendar}>
                        Connect Google Calendar
                    </button>
                    <button className="btn btn-sm btn-outline" onClick={handleSyncCalendar}>
                        Sync Calendar
                    </button>
                    <button className="theme-toggle" onClick={onToggleTheme}>
                        {theme === "dark" ? "Light Mode" : "Dark Mode"}
                    </button>
                    <div className="user-profile">
                        <span>{user ? (user.displayName || user.email) : "Sign In"}</span>
                        {user && (
                            <button className="btn btn-sm btn-outline" onClick={() => authSignOut(auth)}>
                                Sign Out
                            </button>
                        )}
                    </div>
                </div>

                {/* Mobile Nav Actions */}
                <div className="mobile-menu-container">
                    <button className="mobile-menu-toggle" onClick={() => setMenuOpen(!menuOpen)}>
                        <span>{user ? (user.displayName || user.email) : "Sign In"}</span>
                        <svg className={`chevron-icon ${menuOpen ? 'open' : ''}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                    {menuOpen && (
                        <div className="mobile-dropdown-menu">
                            <button className="dropdown-item" onClick={() => { setProfileOpen(true); setMenuOpen(false); }}>
                                Family Profile
                            </button>
                            <button className="dropdown-item" onClick={() => { handleConnectCalendar(); setMenuOpen(false); }}>
                                Connect Google Calendar
                            </button>
                            <button className="dropdown-item" onClick={() => { handleSyncCalendar(); setMenuOpen(false); }}>
                                Sync Calendar
                            </button>
                            <button className="dropdown-item" onClick={() => { onToggleTheme(); setMenuOpen(false); }}>
                                {theme === "dark" ? "Light Mode" : "Dark Mode"}
                            </button>
                            {user && (
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
                            placeholder="e.g., Emily is registered for Soccer Camp from July 6 to July 10, daily 9:00 to 12:00..."
                            value={ingestText}
                            onChange={(e) => setIngestText(e.target.value)}
                        />

                        <div className="ingest-options">
                            <label className="checkbox-label">
                                <input
                                    type="checkbox"
                                    checked={isDisruption}
                                    onChange={(e) => setIsDisruption(e.target.checked)}
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

                    <div className="matrix-grid">
                        {loadError ? (
                            <div className="loading-placeholder" style={{ color: "var(--danger-text)" }}>
                                Error loading schedule: {loadError}
                            </div>
                        ) : matrix && profile ? (
                            <MatrixGrid matrix={matrix} profile={profile} />
                        ) : (
                            <div className="loading-placeholder">Loading schedule matrix...</div>
                        )}
                    </div>
                </main>
            </div>

            {profileOpen && (
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
        </div>
    );
}
