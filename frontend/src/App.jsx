import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { auth, authOnStateChanged } from "./firebase.js";
import { apiFetch } from "./api.js";
import AppShellBoot from "./components/AppShellBoot.jsx";
import { trackEvent, trackPageView, reportWebVitals } from "./analytics.js";

const AuthView = lazy(() => import("./components/AuthView.jsx"));
const OnboardingView = lazy(() => import("./components/OnboardingView.jsx"));
const Dashboard = lazy(() => import("./components/Dashboard.jsx"));

const DEMO_STORAGE_KEY = "insummery_demo_mode";

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

    useEffect(() => {
        if (view === "loading") return;
        trackPageView(view);
        reportWebVitals(view);
    }, [view]);

    const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

    const enterDemo = useCallback(async () => {
        const [{ DEMO_USER, DEMO_PROFILE }, { loadDemoMatrix, restoreSeedDemoMatrix }] =
            await Promise.all([
                import("./demo/demoData.js"),
                import("./demo/demoStore.js"),
            ]);
        localStorage.setItem(DEMO_STORAGE_KEY, "1");
        restoreSeedDemoMatrix();
        setDemoMode(true);
        setUser(DEMO_USER);
        setToken("demo-local-token");
        setProfile(DEMO_PROFILE);
        setMatrix(loadDemoMatrix());
        setLoadError(null);
        setView("dashboard");
        trackEvent("demo_enter");
    }, []);

    const exitDemo = useCallback(() => {
        localStorage.removeItem(DEMO_STORAGE_KEY);
        setDemoMode(false);
        setUser(null);
        setToken(null);
        setProfile(null);
        setMatrix(null);
        setView("auth");
        trackEvent("demo_exit");
    }, []);

    useEffect(() => {
        if (demoMode) {
            let cancelled = false;
            (async () => {
                const [{ DEMO_USER, DEMO_PROFILE }, { loadDemoMatrix }] = await Promise.all([
                    import("./demo/demoData.js"),
                    import("./demo/demoStore.js"),
                ]);
                if (cancelled) return;
                setUser(DEMO_USER);
                setToken("demo-local-token");
                setProfile(DEMO_PROFILE);
                setMatrix((current) => current ?? loadDemoMatrix());
                setLoadError(null);
                setView("dashboard");
            })();
            return () => {
                cancelled = true;
            };
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
            const [{ DEMO_PROFILE }, { loadDemoMatrix }] = await Promise.all([
                import("./demo/demoData.js"),
                import("./demo/demoStore.js"),
            ]);
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
            (async () => {
                const [{ DEMO_PROFILE }, { loadDemoMatrix }] = await Promise.all([
                    import("./demo/demoData.js"),
                    import("./demo/demoStore.js"),
                ]);
                setProfile(DEMO_PROFILE);
                setMatrix(loadDemoMatrix());
                setLoadError(null);
            })();
            return;
        }
        if (token) loadDashboardData(token);
    }, [token, loadDashboardData, demoMode]);

    if (view === "loading") {
        return <AppShellBoot />;
    }

    return (
        <Suspense fallback={<AppShellBoot />}>
            {view === "auth" && <AuthView onStartDemo={enterDemo} />}
            {view === "onboarding" && (
                <OnboardingView user={user} token={token} onCompleted={reload} />
            )}
            {view === "dashboard" && (
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
            )}
        </Suspense>
    );
}
