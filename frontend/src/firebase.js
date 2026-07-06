import { initializeApp } from "firebase/app";
import {
    getAuth,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    GoogleAuthProvider,
    signOut,
    onAuthStateChanged
} from "firebase/auth";

// Firebase configuration (uses local emulator config by default, can be customized)
const firebaseConfig = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY || "mock-api-key",
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "insummery-ai.firebaseapp.com",
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "insummery-ai",
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || "insummery-ai.appspot.com",
    messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || "123456789",
    appId: import.meta.env.VITE_FIREBASE_APP_ID || "1:123456789:web:abcdef"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export { GoogleAuthProvider };

// API URL (default to local emulator, can be overridden at build time)
export const API_URL =
    import.meta.env.VITE_API_URL || "http://127.0.0.1:5001/insummery-ai/us-central1/api";

// Firebase Hosting's `/api/**` rewrite hard-caps proxied requests at 60s no
// matter how the Cloud Function itself is configured (see
// https://firebase.google.com/docs/hosting/functions#direct-requests-to-function).
// The email-processing workflow chains several LLM calls and can exceed that
// on a cold instance, which Hosting surfaces to the browser as a 503. Slow
// endpoints call the function's direct Cloud Functions URL instead, which
// has no such proxy timeout. Defaults to API_URL so local/emulator dev
// (which has no 60s cap) needs no extra configuration.
export const DIRECT_API_URL = import.meta.env.VITE_DIRECT_API_URL || API_URL;

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
        const parsed = JSON.parse(savedUser);
        parsed.getIdToken = async () => "mock-firebase-id-token";
        mockAuth.currentUser = parsed;
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

// Wrapped Auth Functions (mock in emulator mode, real Firebase otherwise)
export const authSignIn = useMockAuth ? mockSignInWithEmailAndPassword : signInWithEmailAndPassword;
export const authSignUp = useMockAuth ? mockCreateUserWithEmailAndPassword : createUserWithEmailAndPassword;
export const authSignInPopup = useMockAuth ? mockSignInWithPopup : signInWithPopup;
export const authSignOut = useMockAuth ? mockSignOut : signOut;
export const authOnStateChanged = useMockAuth ? mockOnAuthStateChanged : onAuthStateChanged;
