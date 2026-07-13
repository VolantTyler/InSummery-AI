import { useCallback, useEffect, useState } from "react";
import { auth, authOnStateChanged } from "./firebase.js";
import { apiFetch } from "./api.js";
import AuthView from "./components/AuthView.jsx";
import OnboardingView from "./components/OnboardingView.jsx";
import Dashboard from "./components/Dashboard.jsx";
import { DEMO_STORAGE_KEY, DEMO_USER, DEMO_PROFILE } from "./demo/demoData.js";
import { loadDemoMatrix, restoreSeedDemoMatrix } from "./demo/demoStore.js";

function isDemoMode() {
    return localStorage.getItem(DEMO_STORAGE_KEY) === "1";
}

export default function App() {
    const [user, setUser] = useState(null);
    const [token, setToken] = useState(null);
    const [view, setView] = useState("loading"); // loading | auth | onboarding | dashboard
    const [profile, setProfile] = useState(null);
    const [matrix, setMatrix] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [demoMode, setDemoMode] = useState(() => isDemoMode());
    const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");

    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("theme", theme);
    }, [theme]);

    const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

    const enterDemo = useCallback(() => {
        localStorage.setItem(DEMO_STORAGE_KEY, "1");
        restoreSeedDemoMatrix();
        setDemoMode(true);
        setUser(DEMO_USER);
        setToken("demo-local-token");
        setProfile(DEMO_PROFILE);
        setMatrix(loadDemoMatrix());
        setLoadError(null);
        setView("dashboard");
    }, []);

    const exitDemo = useCallback(() => {
        localStorage.removeItem(DEMO_STORAGE_KEY);
        setDemoMode(false);
        setUser(null);
        setToken(null);
        setProfile(null);
        setMatrix(null);
        setView("auth");
    }, []);

    useEffect(() => {
        if (demoMode) {
            setUser(DEMO_USER);
            setToken("demo-local-token");
            setProfile(DEMO_PROFILE);
            setMatrix(loadDemoMatrix());
            setLoadError(null);
            setView("dashboard");
            return undefined;
        }

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
    }, [demoMode]);

    const loadDashboardData = useCallback(async (t) => {
        if (demoMode || t === "demo-local-token") {
            setProfile(DEMO_PROFILE);
            setMatrix(loadDemoMatrix());
            setLoadError(null);
            setView("dashboard");
            return;
        }

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
    }, [demoMode]);

    useEffect(() => {
        if (token && !demoMode) {
            loadDashboardData(token);
        }
    }, [token, loadDashboardData, demoMode]);

    const reload = useCallback(() => {
        if (demoMode) {
            setProfile(DEMO_PROFILE);
            setMatrix(loadDemoMatrix());
            setLoadError(null);
            return;
        }
        if (token) loadDashboardData(token);
    }, [token, loadDashboardData, demoMode]);

    if (view === "loading") {
        return null;
    }

    if (view === "auth") {
        return <AuthView onStartDemo={enterDemo} />;
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
            demoMode={demoMode}
            onExitDemo={exitDemo}
            onMatrixChange={setMatrix}
        />
    );
}
