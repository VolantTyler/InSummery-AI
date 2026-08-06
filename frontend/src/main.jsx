import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { initAnalytics, reportWebVitals } from "./analytics.js";
import "./index.css";

// Apply the persisted theme before first paint to avoid a flash of the wrong theme.
const savedTheme = localStorage.getItem("theme") || "light";
document.documentElement.setAttribute("data-theme", savedTheme);

initAnalytics();
reportWebVitals("boot");

const rootEl = document.getElementById("root");
// Remove the static HTML boot shell once React mounts.
const boot = document.getElementById("app-boot");
if (boot) boot.remove();

createRoot(rootEl).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>
);
