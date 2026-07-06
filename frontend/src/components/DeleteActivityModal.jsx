import React from "react";

export default function DeleteActivityModal({ activity, onDelete, onClose }) {
    if (!activity) return null;

    // Format date beautifully
    const eventDate = new Date(activity.date + "T00:00:00").toLocaleDateString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric"
    });

    const isSeries = activity.start_date !== activity.end_date;

    const startDateStr = new Date(activity.start_date + "T00:00:00").toLocaleDateString("en-US", {
        month: "short",
        day: "numeric"
    });
    const endDateStr = new Date(activity.end_date + "T00:00:00").toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric"
    });

    return (
        <div className="modal-overlay">
            <div className="modal-card">
                <div className="modal-header">
                    <h3>Delete Activity</h3>
                    <button className="modal-close" onClick={onClose}>&times;</button>
                </div>
                <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <p style={{ color: "var(--text-muted)" }}>
                        How would you like to delete this activity?
                    </p>
                    
                    <div style={{
                        padding: "16px",
                        backgroundColor: "var(--bg-color)",
                        borderRadius: "12px",
                        border: "1px solid var(--border-color)",
                        display: "flex",
                        flexDirection: "column",
                        gap: "6px"
                    }}>
                        <div style={{ fontWeight: "700", color: "var(--primary)", fontSize: "16px" }}>
                            {activity.title}
                        </div>
                        {isSeries && (
                            <div style={{ fontSize: "13px", color: "var(--text-muted)", fontWeight: "500" }}>
                                Series: {startDateStr} - {endDateStr}
                            </div>
                        )}
                        <div style={{ fontSize: "13px", color: "var(--text-muted)", fontWeight: "500" }}>
                            Target Date: {eventDate}
                        </div>
                    </div>
                </div>
                <div className="modal-footer" style={{ display: "flex", gap: "12px", justifyContent: "flex-end", flexWrap: "wrap", marginTop: "24px" }}>
                    <button className="btn btn-outline" onClick={onClose}>
                        Cancel
                    </button>
                    {isSeries && (
                        <button className="btn btn-outline btn-outline-danger" onClick={() => onDelete("single")}>
                            Delete This Event Only
                        </button>
                    )}
                    <button className="btn btn-danger" onClick={() => onDelete("series")}>
                        {isSeries ? "Delete Entire Series" : "Delete Activity"}
                    </button>
                </div>
            </div>
        </div>
    );
}
