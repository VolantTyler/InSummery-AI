import { useState } from "react";
import { auth, authSignIn, authSignUp, authSignInPopup, GoogleAuthProvider } from "../firebase.js";
import BrandLogo from "./BrandLogo.jsx";

function GoogleIcon() {
    return (
        <svg className="google-icon" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z" />
            <path fill="#34A853" d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z" />
            <path fill="#FBBC05" d="M11.69 28.18C11.25 26.86 11 25.45 11 24s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z" />
            <path fill="#EA4335" d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 12.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z" />
        </svg>
    );
}

function friendlyAuthError(err) {
    const text = `${err.code || ""} ${err.message || ""}`;
    if (text.includes("auth/configuration-not-found")) {
        return "Sign-in isn't fully set up for this Firebase project yet. An administrator needs to enable Authentication (and the Google provider) in the Firebase console. See the README for setup steps.";
    }
    if (text.includes("auth/popup-closed-by-user")) {
        return "The Google sign-in window was closed before finishing. Please try again.";
    }
    if (text.includes("auth/unauthorized-domain")) {
        return "This domain isn't authorized for sign-in. An administrator needs to add it under Authentication > Settings > Authorized domains in the Firebase console.";
    }
    return err.message;
}

export default function AuthView() {
    const [isSignUpMode, setIsSignUpMode] = useState(false);
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(null);
        setLoading(true);
        try {
            if (isSignUpMode) {
                await authSignUp(auth, email, password);
            } else {
                await authSignIn(auth, email, password);
            }
        } catch (err) {
            setError(friendlyAuthError(err));
            setLoading(false);
        }
    };

    const handleGoogle = async () => {
        setError(null);
        setLoading(true);
        const provider = new GoogleAuthProvider();
        try {
            await authSignInPopup(auth, provider);
        } catch (err) {
            setError(friendlyAuthError(err));
            setLoading(false);
        }
    };

    const switchMode = (e) => {
        e.preventDefault();
        setError(null);
        setIsSignUpMode(m => !m);
    };

    return (
        <div id="auth-view" className="view">
            <div className="auth-card">
                <div className="auth-header">
                    <BrandLogo size={56} textClassName="auth-brand-title" />
                    <p>Your Family Schedule Concierge</p>
                </div>

                <h3 className="auth-mode-heading">
                    {isSignUpMode ? "Create your account" : "Sign in to your account"}
                </h3>

                {error && <div className="alert alert-danger">{error}</div>}

                <form onSubmit={handleSubmit}>
                    <div className="form-group">
                        <label htmlFor="email">Email Address</label>
                        <input
                            type="email"
                            id="email"
                            required
                            placeholder="you@example.com"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            disabled={loading}
                        />
                    </div>
                    <div className="form-group">
                        <label htmlFor="password">Password</label>
                        <input
                            type="password"
                            id="password"
                            required
                            placeholder="••••••••"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            disabled={loading}
                        />
                    </div>
                    <button
                        type="submit"
                        className={`btn btn-block ${isSignUpMode ? "btn-primary" : "btn-signin"}`}
                        disabled={loading}
                    >
                        {loading && <span className="spinner"></span>}
                        {isSignUpMode ? "Sign Up" : "Sign In"}
                    </button>
                </form>

                <div className="auth-divider">
                    <span>or</span>
                </div>

                <button className="btn btn-outline btn-block" onClick={handleGoogle} disabled={loading}>
                    {loading ? <span className="spinner spinner-dark"></span> : <GoogleIcon />}
                    {isSignUpMode ? "Sign up with Google" : "Sign in with Google"}
                </button>

                <div className="auth-footer">
                    <p>
                        {isSignUpMode ? "Already have an account?" : "Don't have an account?"}{" "}
                        <a href="#" onClick={loading ? undefined : switchMode}>
                            {isSignUpMode ? "Sign In" : "Sign Up"}
                        </a>
                    </p>
                </div>
            </div>
        </div>
    );
}
