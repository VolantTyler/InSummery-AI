import { API_URL, DIRECT_API_URL } from "./firebase.js";

export async function apiFetch(token, endpoint, options = {}) {
    const { baseUrl = API_URL, ...fetchOptions } = options;
    const headers = {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        ...(fetchOptions.headers || {})
    };

    const response = await fetch(`${baseUrl}/${endpoint}`, {
        ...fetchOptions,
        headers
    });

    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP error ${response.status}`);
    }

    return response.json();
}
