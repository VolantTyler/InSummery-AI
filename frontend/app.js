// Import Firebase features from window (loaded via CDN in index.html)
const {
    initializeApp,
    getAuth,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    GoogleAuthProvider,
    signOut,
    onAuthStateChanged
} = window.FirebaseLib;

// Firebase configuration (uses local emulator config by default, can be customized)
const firebaseConfig = {
    apiKey: "mock-api-key",
    authDomain: "insummery-ai.firebaseapp.com",
    projectId: "insummery-ai",
    storageBucket: "insummery-ai.appspot.com",
    messagingSenderId: "123456789",
    appId: "1:123456789:web:abcdef"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// API URL (default to local emulator, can be overridden)
const API_URL = "http://127.0.0.1:5001/insummery-ai/us-central1/api";

// Check if we should use mock auth (if API key is mock-api-key or invalid)
const useMockAuth = firebaseConfig.apiKey === "mock-api-key";

// Mock Auth State
let mockAuthStateListener = null;
const mockAuth = {
    currentUser: null,
    async getIdToken() {
        return "mock-firebase-id-token";
    }
};

// Initialize mock user from localStorage
if (useMockAuth) {
    const savedUser = localStorage.getItem("mock_current_user");
    if (savedUser) {
        mockAuth.currentUser = JSON.parse(savedUser);
    }
}

// Mock Auth Functions
const mockSignInWithEmailAndPassword = async (authObj, email, password) => {
    const users = JSON.parse(localStorage.getItem("mock_users") || "[]");
    const user = users.find(u => u.email === email);
    if (!user) {
        throw new Error("Firebase: Error (auth/user-not-found).");
    }
    if (user.password !== password) {
        throw new Error("Firebase: Error (auth/wrong-password).");
    }
    const currentUserObj = { email, displayName: email.split("@")[0], getIdToken: async () => "mock-firebase-id-token" };
    mockAuth.currentUser = currentUserObj;
    localStorage.setItem("mock_current_user", JSON.stringify(currentUserObj));
    if (mockAuthStateListener) mockAuthStateListener(currentUserObj);
    return { user: currentUserObj };
};

const mockCreateUserWithEmailAndPassword = async (authObj, email, password) => {
    const users = JSON.parse(localStorage.getItem("mock_users") || "[]");
    if (users.some(u => u.email === email)) {
        throw new Error("Firebase: Error (auth/email-already-in-use).");
    }
    users.push({ email, password });
    localStorage.setItem("mock_users", JSON.stringify(users));
    
    const currentUserObj = { email, displayName: email.split("@")[0], getIdToken: async () => "mock-firebase-id-token" };
    mockAuth.currentUser = currentUserObj;
    localStorage.setItem("mock_current_user", JSON.stringify(currentUserObj));
    if (mockAuthStateListener) mockAuthStateListener(currentUserObj);
    return { user: currentUserObj };
};

const mockSignInWithPopup = async (authObj, provider) => {
    const email = prompt("Enter Google Account Email to Sign In (SSO Simulation):", "tyler@example.com");
    if (!email) {
        throw new Error("Firebase: Error (auth/popup-closed-by-user).");
    }
    const currentUserObj = { email, displayName: email.split("@")[0], getIdToken: async () => "mock-firebase-id-token" };
    mockAuth.currentUser = currentUserObj;
    localStorage.setItem("mock_current_user", JSON.stringify(currentUserObj));
    if (mockAuthStateListener) mockAuthStateListener(currentUserObj);
    return { user: currentUserObj };
};

const mockSignOut = async (authObj) => {
    mockAuth.currentUser = null;
    localStorage.removeItem("mock_current_user");
    if (mockAuthStateListener) mockAuthStateListener(null);
};

const mockOnAuthStateChanged = (authObj, callback) => {
    mockAuthStateListener = callback;
    // Trigger initial state
    setTimeout(() => {
        callback(mockAuth.currentUser);
    }, 50);
    return () => { mockAuthStateListener = null; };
};

// Wrap Auth Functions
const authSignIn = useMockAuth ? mockSignInWithEmailAndPassword : signInWithEmailAndPassword;
const authSignUp = useMockAuth ? mockCreateUserWithEmailAndPassword : createUserWithEmailAndPassword;
const authSignInPopup = useMockAuth ? mockSignInWithPopup : signInWithPopup;
const authSignOut = useMockAuth ? mockSignOut : signOut;
const authOnStateChanged = useMockAuth ? mockOnAuthStateChanged : onAuthStateChanged;

// State
let currentUser = null;
let currentToken = null;
let pendingWorkflowId = null;

// DOM Elements
const authView = document.getElementById("auth-view");
const dashboardView = document.getElementById("dashboard-view");
const authError = document.getElementById("auth-error");
const loginForm = document.getElementById("login-form");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const btnLogin = document.getElementById("btn-login");
const btnGoogle = document.getElementById("btn-google");
const linkToggleSignup = document.getElementById("link-toggle-signup");
const btnLogout = document.getElementById("btn-logout");
const userDisplayName = document.getElementById("user-display-name");
const btnThemeToggle = document.getElementById("btn-theme-toggle");

const ingestInput = document.getElementById("ingest-input");
const checkDisruption = document.getElementById("check-disruption");
const btnSubmitIngest = document.getElementById("btn-submit-ingest");
const ingestStatus = document.getElementById("ingest-status");

const gapsList = document.getElementById("gaps-list");
const disruptionsList = document.getElementById("disruptions-list");
const matrixContainer = document.getElementById("matrix-container");

const hitlModal = document.getElementById("hitl-modal");
const hitlQuestionText = document.getElementById("hitl-question-text");
const hitlResponseInput = document.getElementById("hitl-response-input");
const btnSubmitHitl = document.getElementById("btn-submit-hitl");

// Auth Mode
let isSignUpMode = false;

// Initialize Theme
const savedTheme = localStorage.getItem("theme") || "light";
document.documentElement.setAttribute("data-theme", savedTheme);
btnThemeToggle.textContent = savedTheme === "dark" ? "Light Mode" : "Dark Mode";

// Event Listeners
btnThemeToggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const newTheme = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", newTheme);
    localStorage.setItem("theme", newTheme);
    btnThemeToggle.textContent = newTheme === "dark" ? "Light Mode" : "Dark Mode";
});

linkToggleSignup.addEventListener("click", (e) => {
    e.preventDefault();
    isSignUpMode = !isSignUpMode;
    if (isSignUpMode) {
        btnLogin.textContent = "Sign Up";
        linkToggleSignup.textContent = "Sign In";
        document.querySelector(".auth-header p").textContent = "Create your Summify account";
    } else {
        btnLogin.textContent = "Sign In";
        linkToggleSignup.textContent = "Sign Up";
        document.querySelector(".auth-header p").textContent = "Your Family Schedule Concierge";
    }
});

// Authentication Handlers
loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    authError.classList.add("hidden");
    const email = emailInput.value;
    const password = passwordInput.value;
    
    try {
        if (isSignUpMode) {
            await authSignUp(auth, email, password);
        } else {
            await authSignIn(auth, email, password);
        }
    } catch (err) {
        authError.textContent = err.message;
        authError.classList.remove("hidden");
    }
});

btnGoogle.addEventListener("click", async () => {
    authError.classList.add("hidden");
    const provider = new GoogleAuthProvider();
    try {
        await authSignInPopup(auth, provider);
    } catch (err) {
        authError.textContent = err.message;
        authError.classList.remove("hidden");
    }
});

btnLogout.addEventListener("click", () => {
    authSignOut(auth);
});

// Listen for Auth State Changes
authOnStateChanged(auth, async (user) => {
    if (user) {
        currentUser = user;
        currentToken = await user.getIdToken();
        userDisplayName.textContent = user.displayName || user.email;
        
        authView.classList.add("hidden");
        dashboardView.classList.remove("hidden");
        
        // Load Matrix & Profile
        loadDashboardData();
    } else {
        currentUser = null;
        currentToken = null;
        authView.classList.remove("hidden");
        dashboardView.classList.add("hidden");
    }
});

// Fetch API Helper
async function apiFetch(endpoint, options = {}) {
    const headers = {
        "Authorization": `Bearer ${currentToken}`,
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

// Ingest Schedule Handler
btnSubmitIngest.addEventListener("click", async () => {
    const text = ingestInput.value.trim();
    if (!text) return;
    
    showIngestStatus("Processing text with AI...", "loading");
    btnSubmitIngest.disabled = true;
    
    try {
        const res = await apiFetch("process-email", {
            method: "POST",
            body: JSON.stringify({
                text,
                isDisruption: checkDisruption.checked
            })
        });
        
        if (res.status === "INTERRUPTED") {
            pendingWorkflowId = res.workflowId;
            showIngestStatus("Clarification required...", "loading");
            openHitlModal(res.message);
        } else {
            showIngestStatus("Schedule updated successfully!", "success");
            ingestInput.value = "";
            loadDashboardData();
        }
    } catch (err) {
        showIngestStatus(`Error: ${err.message}`, "error");
    } finally {
        btnSubmitIngest.disabled = false;
    }
});

// HITL Resumption Handler
btnSubmitHitl.addEventListener("click", async () => {
    const responseText = hitlResponseInput.value.trim();
    if (!responseText) return;
    
    closeHitlModal();
    showIngestStatus("Resuming AI analysis...", "loading");
    
    try {
        const res = await apiFetch("resume-workflow", {
            method: "POST",
            body: JSON.stringify({
                workflowId: pendingWorkflowId,
                response: responseText
            })
        });
        
        if (res.status === "INTERRUPTED") {
            pendingWorkflowId = res.workflowId;
            openHitlModal(res.message);
        } else {
            showIngestStatus("Schedule updated successfully!", "success");
            ingestInput.value = "";
            loadDashboardData();
        }
    } catch (err) {
        showIngestStatus(`Error: ${err.message}`, "error");
    }
});

function showIngestStatus(msg, type) {
    ingestStatus.textContent = msg;
    ingestStatus.className = `status-indicator status-${type}`;
    ingestStatus.classList.remove("hidden");
}

function openHitlModal(question) {
    hitlQuestionText.textContent = question;
    hitlResponseInput.value = "";
    hitlModal.classList.remove("hidden");
}

function closeHitlModal() {
    hitlModal.classList.add("hidden");
}

// Load Dashboard Data
async function loadDashboardData() {
    try {
        const [matrix, profile] = await Promise.all([
            apiFetch("get-matrix"),
            apiFetch("get-profile")
        ]);
        
        renderMatrix(matrix, profile);
        renderAlerts(matrix);
    } catch (err) {
        console.error("Error loading dashboard data:", err);
        matrixContainer.innerHTML = `<div class="loading-placeholder" style="color: var(--danger-text);">Error loading schedule: ${err.message}</div>`;
    }
}

// Render Matrix Grid
function renderMatrix(matrix, profile) {
    const activities = matrix.activities || [];
    const gaps = matrix.gaps || [];
    
    // Extract unique dates from activities and gaps
    const datesSet = new Set();
    activities.forEach(act => {
        datesSet.add(act.start_date);
        datesSet.add(act.end_date);
    });
    gaps.forEach(gap => datesSet.add(gap.date));
    
    if (datesSet.size === 0) {
        matrixContainer.innerHTML = '<div class="loading-placeholder">No scheduled activities found. Paste an email to get started!</div>';
        return;
    }
    
    const sortedDates = Array.from(datesSet).sort();
    const children = (profile.children || []).map(c => c.name).filter(Boolean);
    const baselines = profile.baseline_coverage || [];
    
    let html = "";
    
    sortedDates.forEach(dateStr => {
        const dateObj = new Date(dateStr + "T00:00:00");
        const dayOfWeek = dateObj.getDay();
        if (dayOfWeek === 0 || dayOfWeek === 6) return; // Weekdays only
        
        const dayName = dateObj.toLocaleDateString("en-US", { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
        
        html += `
            <div class="day-card">
                <div class="day-header">${dayName}</div>
                <div class="children-columns">
        `;
        
        children.forEach(child => {
            const timelineItems = [];
            
            // 1. Add school baseline
            baselines.forEach(baseline => {
                if (isDateInBaseline(dateObj, baseline)) {
                    timelineItems.push({
                        start_time: baseline.start_time,
                        end_time: baseline.end_time,
                        title: baseline.name,
                        class_name: "status-school",
                        notes: "Baseline school hours"
                    });
                }
            });
            
            // 2. Add activities
            activities.forEach(act => {
                if (act.child_name === child) {
                    if (act.start_date <= dateStr && dateStr <= act.end_date) {
                        timelineItems.push({
                            start_time: act.start_time,
                            end_time: act.end_time,
                            title: act.activity_title,
                            class_name: act.status === "ACTIVE" ? "status-active" : "status-disrupted",
                            notes: act.notes || ""
                        });
                    }
                }
            });
            
            // 3. Add gaps
            gaps.forEach(gap => {
                if (gap.child_name === child && gap.date === dateStr) {
                    timelineItems.push({
                        start_time: gap.start_time,
                        end_time: gap.end_time,
                        title: gap.type === "ABSOLUTE" ? "Childcare Gap" : "Sibling Care Mismatch",
                        class_name: "status-gap",
                        notes: gap.description || ""
                    });
                }
            });
            
            // Sort by start time
            timelineItems.sort((a, b) => a.start_time.localeCompare(b.start_time));
            
            html += `
                <div class="child-column">
                    <div class="child-name">${child}</div>
            `;
            
            if (timelineItems.length > 0) {
                timelineItems.forEach(item => {
                    html += `
                        <div class="timeline-item ${item.class_name}">
                            <div class="item-time">${item.start_time} - ${item.end_time}</div>
                            <div class="item-title">${item.title}</div>
                            ${item.notes ? `<div class="item-notes">${item.notes}</div>` : ""}
                        </div>
                    `;
                });
            } else {
                html += `<div class="no-alerts" style="padding: 20px 0;">No activities</div>`;
            }
            
            html += `</div>`; // Close child column
        });
        
        html += `
                </div>
            </div>
        `;
    });
    
    matrixContainer.innerHTML = html;
}

// Render Gaps & Disruptions in Sidebar
function renderAlerts(matrix) {
    const gaps = matrix.gaps || [];
    const activities = matrix.activities || [];
    
    // Render Gaps
    if (gaps.length > 0) {
        gapsList.innerHTML = gaps.map(gap => `
            <div class="alert-item ${gap.type === 'ABSOLUTE' ? 'alert-absolute' : 'alert-relative'}">
                <strong>${gap.child_name}</strong> (${gap.date})<br>
                ${gap.start_time} - ${gap.end_time}<br>
                <span style="font-size: 12px; opacity: 0.9;">${gap.description}</span>
            </div>
        `).join("");
    } else {
        gapsList.innerHTML = '<div class="no-alerts">No active childcare gaps!</div>';
    }
    
    // Render Disruptions
    const disruptions = activities.filter(act => act.status === "DISRUPTED");
    if (disruptions.length > 0) {
        disruptionsList.innerHTML = disruptions.map(dis => `
            <div class="alert-item alert-disruption">
                <strong>${dis.child_name}</strong> (${dis.start_date})<br>
                ${dis.start_time} - ${dis.end_time}<br>
                <span style="font-size: 12px; opacity: 0.9;">${dis.notes || "Activity disrupted"}</span>
            </div>
        `).join("");
    } else {
        disruptionsList.innerHTML = '<div class="no-alerts">No active disruptions.</div>';
    }
}

// Helper: Check if date matches baseline config
function isDateInBaseline(date, baseline) {
    const start = new Date(baseline.start_date + "T00:00:00");
    const end = new Date(baseline.end_date + "T00:00:00");
    
    if (date < start || date > end) return false;
    
    // Check days of week
    const daysOfWeek = baseline.days_of_week || [1, 2, 3, 4, 5];
    return daysOfWeek.includes(date.getDay());
}
