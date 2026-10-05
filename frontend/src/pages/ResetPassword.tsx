import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import Logo from "../components/Logo";
import ThemeToggle from "../components/ThemeToggle";
import { api } from "../services/api";

export default function ResetPassword() {
  const navigate = useNavigate();
  const [token] = useState(() => new URLSearchParams(window.location.search).get("token") ?? "");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  // The token is a secret: take it out of the address bar so it doesn't linger in history or screenshots.
  useEffect(() => { window.history.replaceState(null, "", window.location.pathname); }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) { setError("The two passwords don't match."); return; }
    setError(""); setBusy(true);
    try {
      await api("/auth/reset-password", { method: "POST", body: JSON.stringify({ token, password }) });
      setDone(true);
      setTimeout(() => navigate("/login", { replace: true }), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally { setBusy(false); }
  }

  const field = "mt-1 w-full rounded-lg border border-line bg-card px-3 py-2";
  return (
    <div className="grid min-h-screen place-items-center p-4">
      <meta name="referrer" content="no-referrer" />
      <ThemeToggle className="fixed right-4 top-4" />
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-line bg-card p-6">
        <div className="flex items-center gap-2 text-accent"><Logo /><span className="text-lg font-semibold text-ink">MemoryAI</span></div>
        <h1 className="text-xl font-semibold">Choose a new password</h1>
        {!token ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">This reset link is incomplete. <Link to="/forgot-password" className="underline">Request a new one</Link>.</p>
        ) : done ? (
          <p role="status" className="text-sm">Password changed. You were signed out everywhere. Taking you to log in…</p>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="block text-sm">New password
              <input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
              <span className="text-xs text-mute">At least 8 characters.</span>
            </label>
            <label className="block text-sm">Confirm new password
              <input type="password" required minLength={8} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={field} />
            </label>
            {error && (
              <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}{" "}
                {error.includes("invalid or has expired") && <Link to="/forgot-password" className="underline">Request a new link</Link>}</p>
            )}
            <button disabled={busy} className="w-full rounded-lg bg-accent py-2 font-medium text-accent-ink disabled:opacity-60">{busy ? "Please wait…" : "Change password"}</button>
          </form>
        )}
      </div>
    </div>
  );
}
