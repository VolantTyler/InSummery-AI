export default function AlertsSidebar({ matrix }) {
    const gaps = matrix?.gaps || [];
    const activities = matrix?.activities || [];
    const disruptions = activities.filter(act => act.status === "DISRUPTED");

    return (
        <>
            <div className="sidebar-card">
                <h3>Active Gaps</h3>
                <div className="alerts-container">
                    {gaps.length > 0 ? (
                        gaps.map((gap, idx) => (
                            <div
                                className={`alert-item ${gap.type === "ABSOLUTE" ? "alert-absolute" : "alert-relative"}`}
                                key={idx}
                            >
                                <strong>{gap.child_name}</strong> ({gap.date})<br />
                                {gap.start_time} - {gap.end_time}<br />
                                <span style={{ fontSize: "12px", opacity: 0.9 }}>{gap.description}</span>
                            </div>
                        ))
                    ) : (
                        <div className="no-alerts">No active childcare gaps!</div>
                    )}
                </div>
            </div>

            <div className="sidebar-card">
                <h3>Disruptions & Warnings</h3>
                <div className="alerts-container">
                    {disruptions.length > 0 ? (
                        disruptions.map((dis, idx) => (
                            <div className="alert-item alert-disruption" key={idx}>
                                <strong>{dis.child_name}</strong> ({dis.start_date})<br />
                                {dis.start_time} - {dis.end_time}<br />
                                <span style={{ fontSize: "12px", opacity: 0.9 }}>{dis.notes || "Activity disrupted"}</span>
                            </div>
                        ))
                    ) : (
                        <div className="no-alerts">No active disruptions.</div>
                    )}
                </div>
            </div>
        </>
    );
}
