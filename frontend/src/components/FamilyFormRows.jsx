// Shared row editors for parents, children, and caregivers, used by both
// the onboarding form and the profile settings modal.

export const newPerson = (name = "", email = "", phone = "") => ({
    key: crypto.randomUUID(),
    name,
    email,
    phone
});

export const newChild = (name = "", age = "") => ({
    key: crypto.randomUUID(),
    name,
    age
});

export function PersonRow({ row, namePlaceholder, nameRequired, onChange, onRemove }) {
    const update = (field) => (e) => onChange({ ...row, [field]: e.target.value });
    return (
        <div className="form-row">
            <input
                type="text"
                placeholder={namePlaceholder}
                value={row.name}
                required={nameRequired}
                onChange={update("name")}
            />
            <input type="email" placeholder="Email (optional)" value={row.email} onChange={update("email")} />
            <input type="text" placeholder="Phone (optional)" value={row.phone} onChange={update("phone")} />
            <button type="button" className="btn-remove-row" onClick={onRemove}>&times;</button>
        </div>
    );
}

export function ChildRow({ row, onChange, onRemove }) {
    const update = (field) => (e) => onChange({ ...row, [field]: e.target.value });
    return (
        <div className="form-row">
            <input
                type="text"
                placeholder="Child's Name"
                value={row.name}
                required
                onChange={update("name")}
            />
            <input
                type="number"
                placeholder="Age"
                value={row.age}
                required
                min="0"
                max="18"
                onChange={update("age")}
            />
            <button type="button" className="btn-remove-row" onClick={onRemove}>&times;</button>
        </div>
    );
}

// Convert edited rows back into the profile payload shape, dropping empty rows.
export function collectPersons(rows) {
    return rows
        .filter(r => r.name.trim())
        .map(r => ({ name: r.name.trim(), email: r.email.trim(), phone: r.phone.trim() }));
}

export function collectChildren(rows) {
    return rows
        .filter(r => r.name.trim() && r.age !== "")
        .map(r => ({ name: r.name.trim(), age: parseInt(r.age, 10) }));
}
