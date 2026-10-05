import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Logo from "../components/Logo";
import ThemeToggle from "../components/ThemeToggle";
import { useAuth } from "../hooks/useAuth";

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { status, login, register } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  if (status === "authed") return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      await (isLogin ? login : register)(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally { setBusy(false); }
  }

  const field = "mt-1 w-full rounded-lg border border-line bg-card px-3 py-2";
  return (
    <div className="grid min-h-screen place-items-center p-4">
      <ThemeToggle className="fixed right-4 top-4" />
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-line bg-card p-6">
        <div className="flex items-center gap-2 text-accent"><Logo /><span className="text-lg font-semibold text-ink">MemoryAI</span></div>
        <h1 className="text-xl font-semibold">{isLogin ? "Log in" : "Create your account"}</h1>
        <label className="block text-sm">Email
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </label>
        <label className="block text-sm">Password
          <input type="password" required minLength={isLogin ? 1 : 8} autoComplete={isLogin ? "current-password" : "new-password"}
            value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
          {!isLogin && <span className="text-xs text-mute">At least 8 characters.</span>}
        </label>
        {isLogin && <Link to="/forgot-password" className="block text-right text-sm text-accent underline">Forgot password?</Link>}
        {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-accent py-2 font-medium text-accent-ink disabled:opacity-60">
          {busy ? "Please wait…" : isLogin ? "Log in" : "Create account"}
        </button>
        <p className="text-sm text-mute">
          {isLogin ? "New here? " : "Already have an account? "}
          <Link to={isLogin ? "/register" : "/login"} className="text-accent underline">{isLogin ? "Create an account" : "Log in"}</Link>
        </p>
      </form>
    </div>
  );
}
