import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import Logo from "../components/Logo";
import ThemeToggle from "../components/ThemeToggle";
import { api } from "../services/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      await api("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally { setBusy(false); }
  }

  return (
    <div className="grid min-h-screen place-items-center p-4">
      <ThemeToggle className="fixed right-4 top-4" />
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-line bg-card p-6">
        <div className="flex items-center gap-2 text-accent"><Logo /><span className="text-lg font-semibold text-ink">MemoryAI</span></div>
        <h1 className="text-xl font-semibold">Forgot your password?</h1>
        {sent ? (
          <p role="status" className="text-sm">If that email is registered, a reset link is on its way. It works for 30 minutes. Check your spam folder too.</p>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <p className="text-sm text-mute">Enter your email and we'll send a link to choose a new password.</p>
            <label className="block text-sm">Email
              <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line bg-card px-3 py-2" />
            </label>
            {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
            <button disabled={busy} className="w-full rounded-lg bg-accent py-2 font-medium text-accent-ink disabled:opacity-60">{busy ? "Please wait…" : "Send reset link"}</button>
          </form>
        )}
        <Link to="/login" className="block text-sm text-accent underline">Back to log in</Link>
      </div>
    </div>
  );
}
