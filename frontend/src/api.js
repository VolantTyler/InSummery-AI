import { API_URL } from "./firebase.js";

export async function apiFetch(token, endpoint, options = {}) {
    const headers = {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    const response = await fetch(`${API_URL}/${endpoint}`, {
        ...options,
        headers
    });

    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP error ${response.status}`);
    }

    return response.json();
}
