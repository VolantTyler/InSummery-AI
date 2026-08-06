/** Minimal first-paint shell shown while auth/view chunks load. */
export default function AppShellBoot({ message = "Loading your schedule…" }) {
    return (
        <div className="app-shell-boot" role="status" aria-live="polite">
            <div className="app-shell-boot-mark" aria-hidden="true" />
            <p className="app-shell-boot-brand">InSummery</p>
            <p className="app-shell-boot-msg">{message}</p>
        </div>
    );
}
