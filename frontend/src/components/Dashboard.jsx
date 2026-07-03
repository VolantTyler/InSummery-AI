import { useState } from "react";
import { auth, authSignOut } from "../firebase.js";
import { apiFetch } from "../api.js";
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

    return (
        <div id="dashboard-view" className="view">
            <header>
                <div className="header-brand">
                    <h1>InSummery</h1>
                    <span className="badge">Concierge Active</span>
                </div>
                <div className="header-actions">
                    <button className="btn btn-sm btn-outline" onClick={() => setProfileOpen(true)}>
                        Family Profile
                    </button>
                    <button className="theme-toggle" onClick={onToggleTheme}>
                        {theme === "dark" ? "Light Mode" : "Dark Mode"}
                    </button>
                    <div className="user-profile">
                        <span>{user.displayName || user.email}</span>
                        <button className="btn btn-sm btn-outline" onClick={() => authSignOut(auth)}>
                            Sign Out
                        </button>
                    </div>
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
