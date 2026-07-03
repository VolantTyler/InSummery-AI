import { useState } from "react";
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

export default function OnboardingView({ user, token, onCompleted }) {
    // Pre-fill the first parent row with the signed-in user's details.
    const [parents, setParents] = useState(() => [newPerson(user.displayName || "", user.email || "")]);
    const [children, setChildren] = useState(() => [newChild()]);
    const [caregivers, setCaregivers] = useState(() => [newPerson()]);
    const [saving, setSaving] = useState(false);

    const updateRow = (setRows) => (key, updated) =>
        setRows(rows => rows.map(r => (r.key === key ? updated : r)));
    const removeRow = (setRows) => (key) =>
        setRows(rows => rows.filter(r => r.key !== key));

    const handleSubmit = async (e) => {
        e.preventDefault();

        const profileData = {
            parents: collectPersons(parents),
            children: collectChildren(children),
            caregivers: collectPersons(caregivers),
            address: "",
            baseline_coverage: DEFAULT_BASELINE_COVERAGE,
            google_calendar: {
                use_secondary_calendars: false,
                calendar_ids: {}
            }
        };

        setSaving(true);
        try {
            await apiFetch(token, "save-profile", {
                method: "POST",
                body: JSON.stringify(profileData)
            });
            onCompleted();
        } catch (err) {
            alert("Error saving profile: " + err.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div id="onboarding-view" className="view">
            <div className="onboarding-card">
                <div className="onboarding-header">
                    <h2>Welcome to InSummery</h2>
                    <p>Let's set up your family profile to get started.</p>
                </div>

                <form onSubmit={handleSubmit}>
                    <div className="form-section">
                        <h3>Parents / Guardians</h3>
                        <div>
                            {parents.map(row => (
                                <PersonRow
                                    key={row.key}
                                    row={row}
                                    namePlaceholder="Parent Name"
                                    nameRequired
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
                        <h3>Children</h3>
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
                        <h3>Nannies / Caregivers</h3>
                        <div>
                            {caregivers.map(row => (
                                <PersonRow
                                    key={row.key}
                                    row={row}
                                    namePlaceholder="Nanny / Caregiver Name"
                                    nameRequired
                                    onChange={(updated) => updateRow(setCaregivers)(row.key, updated)}
                                    onRemove={() => removeRow(setCaregivers)(row.key)}
                                />
                            ))}
                        </div>
                        <button type="button" className="btn btn-sm btn-outline" onClick={() => setCaregivers(rows => [...rows, newPerson()])}>
                            + Add Caregiver
                        </button>
                    </div>

                    <button type="submit" className="btn btn-primary btn-block" disabled={saving}>
                        {saving ? "Saving..." : "Complete Onboarding"}
                    </button>
                </form>
            </div>
        </div>
    );
}
