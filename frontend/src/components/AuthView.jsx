import { useState } from "react";
import { auth, authSignIn, authSignUp, authSignInPopup, GoogleAuthProvider } from "../firebase.js";

export default function AuthView() {
    const [isSignUpMode, setIsSignUpMode] = useState(false);
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState(null);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(null);
        try {
            if (isSignUpMode) {
                await authSignUp(auth, email, password);
            } else {
                await authSignIn(auth, email, password);
            }
        } catch (err) {
            setError(err.message);
        }
    };

    const handleGoogle = async () => {
        setError(null);
        const provider = new GoogleAuthProvider();
        try {
            await authSignInPopup(auth, provider);
        } catch (err) {
            setError(err.message);
        }
    };

    return (
        <div id="auth-view" className="view">
            <div className="auth-card">
                <div className="auth-header">
                    <h2>InSummery</h2>
                    <p>{isSignUpMode ? "Create your InSummery account" : "Your Family Schedule Concierge"}</p>
                </div>

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
                        />
                    </div>
                    <button type="submit" className="btn btn-primary btn-block">
                        {isSignUpMode ? "Sign Up" : "Sign In"}
                    </button>
                </form>

                <div className="auth-divider">
                    <span>or</span>
                </div>

                <button className="btn btn-outline btn-block" onClick={handleGoogle}>
                    <img
                        src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/action/google.svg"
                        alt="Google Logo"
                        className="google-icon"
                    />
                    Sign in with Google
                </button>

                <div className="auth-footer">
                    <p>
                        Don't have an account?{" "}
                        <a
                            href="#"
                            onClick={(e) => {
                                e.preventDefault();
                                setIsSignUpMode(m => !m);
                            }}
                        >
                            {isSignUpMode ? "Sign In" : "Sign Up"}
                        </a>
                    </p>
                </div>
            </div>
        </div>
    );
}
