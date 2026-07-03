import { useEffect, useState } from "react";
import { apiFetch } from "../api.js";
import {
    PersonRow,
    ChildRow,
    newPerson,
    newChild,
    collectPersons,
    collectChildren
} from "./FamilyFormRows.jsx";

const DEFAULT_BASELINE_COVERAGE = [
    {
        name: "School",
        days: [1, 2, 3, 4, 5],
        start_time: "08:30",
        end_time: "15:00",
        start_date: "2026-09-01",
        end_date: "2027-06-30"
    }
];

export default function ProfileModal({ token, onClose, onSaved }) {
    const [loading, setLoading] = useState(true);
    const [loadErrorMsg, setLoadErrorMsg] = useState(null);
    const [parents, setParents] = useState([]);
    const [children, setChildren] = useState([]);
    const [caregivers, setCaregivers] = useState([]);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const profile = await apiFetch(token, "get-profile");
                if (cancelled) return;

                const loadedParents = (profile.parents || []).map(p => newPerson(p.name, p.email, p.phone));
                const loadedChildren = (profile.children || []).map(c => newChild(c.name, c.age));
                const loadedCaregivers = (profile.caregivers || []).map(cg => newPerson(cg.name, cg.email, cg.phone));

                setParents(loadedParents.length > 0 ? loadedParents : [newPerson()]);
                setChildren(loadedChildren.length > 0 ? loadedChildren : [newChild()]);
                setCaregivers(loadedCaregivers.length > 0 ? loadedCaregivers : [newPerson()]);
                setLoading(false);
            } catch (err) {
                if (cancelled) return;
                setLoadErrorMsg(err.message);
                setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [token]);

    const updateRow = (setRows) => (key, updated) =>
        setRows(rows => rows.map(r => (r.key === key ? updated : r)));
    const removeRow = (setRows) => (key) =>
        setRows(rows => rows.filter(r => r.key !== key));

    const handleSave = async () => {
        setSaving(true);
        try {
            // Fetch current profile to preserve other settings (e.g. baseline_coverage, address, calendar settings)
            let profile = {};
            try {
                profile = await apiFetch(token, "get-profile");
                if (profile.onboarding_required) profile = {};
            } catch {
                // Fallback to empty
            }

            profile.parents = collectPersons(parents);
            profile.children = collectChildren(children);
            profile.caregivers = collectPersons(caregivers);

            // Ensure default structure if missing
            if (!profile.baseline_coverage) {
                profile.baseline_coverage = DEFAULT_BASELINE_COVERAGE;
            }
            if (!profile.google_calendar) {
                profile.google_calendar = {
                    use_secondary_calendars: false,
                    calendar_ids: {}
                };
            }
            if (!profile.address) profile.address = "";

            await apiFetch(token, "save-profile", {
                method: "POST",
                body: JSON.stringify(profile)
            });

            onSaved();
        } catch (err) {
            alert("Error saving profile: " + err.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal-card profile-modal-card">
                <div className="modal-header">
                    <h3>Family Profile Settings</h3>
                    <button className="modal-close" onClick={onClose}>&times;</button>
                </div>
                <div className="modal-body">
                    {loading ? (
                        <div className="loading-placeholder">Loading profile...</div>
                    ) : loadErrorMsg ? (
                        <div style={{ color: "var(--danger-text)" }}>Error: {loadErrorMsg}</div>
                    ) : (
                        <>
                            <div className="form-section">
                                <h4>Parents / Guardians</h4>
                                <div>
                                    {parents.map(row => (
                                        <PersonRow
                                            key={row.key}
                                            row={row}
                                            namePlaceholder="Parent Name"
                                            onChange={(updated) => updateRow(setParents)(row.key, updated)}
                                            onRemove={() => removeRow(setParents)(row.key)}
                                        />
                                    ))}
                                </div>
                                <button type="button" className="btn btn-sm btn-outline" onClick={() => setParents(rows => [...rows, newPerson()])}>
                                    + Add Parent
                                </button>
                            </div>

                            <div className="form-section">
                                <h4>Children</h4>
                                <div>
                                    {children.map(row => (
                                        <ChildRow
                                            key={row.key}
                                            row={row}
                                            onChange={(updated) => updateRow(setChildren)(row.key, updated)}
                                            onRemove={() => removeRow(setChildren)(row.key)}
                                        />
                                    ))}
                                </div>
                                <button type="button" className="btn btn-sm btn-outline" onClick={() => setChildren(rows => [...rows, newChild()])}>
                                    + Add Child
                                </button>
                            </div>

                            <div className="form-section">
                                <h4>Nannies / Caregivers</h4>
                                <div>
                                    {caregivers.map(row => (
                                        <PersonRow
                                            key={row.key}
                                            row={row}
                                            namePlaceholder="Nanny / Caregiver Name"
                                            onChange={(updated) => updateRow(setCaregivers)(row.key, updated)}
                                            onRemove={() => removeRow(setCaregivers)(row.key)}
                                        />
                                    ))}
                                </div>
                                <button type="button" className="btn btn-sm btn-outline" onClick={() => setCaregivers(rows => [...rows, newPerson()])}>
                                    + Add Caregiver
                                </button>
                            </div>
                        </>
                    )}
                </div>
                <div className="modal-footer">
                    <button className="btn btn-primary" onClick={handleSave} disabled={saving || loading}>
                        {saving ? "Saving..." : "Save Changes"}
                    </button>
                </div>
            </div>
        </div>
    );
}
