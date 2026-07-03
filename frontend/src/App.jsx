import { useCallback, useEffect, useState } from "react";
import { auth, authOnStateChanged } from "./firebase.js";
import { apiFetch } from "./api.js";
import AuthView from "./components/AuthView.jsx";
import OnboardingView from "./components/OnboardingView.jsx";
import Dashboard from "./components/Dashboard.jsx";

export default function App() {
    const [user, setUser] = useState(null);
    const [token, setToken] = useState(null);
    const [view, setView] = useState("loading"); // loading | auth | onboarding | dashboard
    const [profile, setProfile] = useState(null);
    const [matrix, setMatrix] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");

    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("theme", theme);
    }, [theme]);

    const toggleTheme = () => setTheme(t => (t === "dark" ? "light" : "dark"));

    useEffect(() => {
        const unsubscribe = authOnStateChanged(auth, async (u) => {
            if (u) {
                const t = await u.getIdToken();
                setUser(u);
                setToken(t);
            } else {
                setUser(null);
                setToken(null);
                setProfile(null);
                setMatrix(null);
                setView("auth");
            }
        });
        return unsubscribe;
    }, []);

    const loadDashboardData = useCallback(async (t) => {
        try {
            const prof = await apiFetch(t, "get-profile");

            if (prof && prof.onboarding_required) {
                setView("onboarding");
                return;
            }

            const mat = await apiFetch(t, "get-matrix");
            setProfile(prof);
            setMatrix(mat);
            setLoadError(null);
            setView("dashboard");
        } catch (err) {
            console.error("Error loading dashboard data:", err);
            setLoadError(err.message);
            setView("dashboard");
        }
    }, []);

    useEffect(() => {
        if (token) {
            loadDashboardData(token);
        }
    }, [token, loadDashboardData]);

    const reload = useCallback(() => {
        if (token) loadDashboardData(token);
    }, [token, loadDashboardData]);

    if (view === "loading") {
        return null;
    }

    if (view === "auth") {
        return <AuthView />;
    }

    if (view === "onboarding") {
        return <OnboardingView user={user} token={token} onCompleted={reload} />;
    }

    return (
        <Dashboard
            user={user}
            token={token}
            profile={profile}
            matrix={matrix}
            loadError={loadError}
            onReload={reload}
            theme={theme}
            onToggleTheme={toggleTheme}
        />
    );
}
