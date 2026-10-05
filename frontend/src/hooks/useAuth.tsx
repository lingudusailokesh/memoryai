import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, refreshSession, setAccessToken } from "../services/api";

export interface User { id: string; email: string }
type Status = "loading" | "authed" | "anon";
interface AuthCtx {
  user: User | null;
  status: Status;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  // On page load the in-memory token is gone: try the refresh cookie to restore the session.
  useEffect(() => {
    let alive = true;
    (async () => {
      if (await refreshSession()) {
        try {
          const me = await api<User>("/me");
          if (alive) { setUser(me); setStatus("authed"); }
          return;
        } catch { /* fall through to anon */ }
      }
      if (alive) setStatus("anon");
    })();
    return () => { alive = false; };
  }, []);

  const start = useCallback(async (path: string, email: string, password: string) => {
    const t = await api<{ access_token: string }>(path, { method: "POST", body: JSON.stringify({ email, password }) });
    setAccessToken(t.access_token);
    setUser(await api<User>("/me"));
    setStatus("authed");
  }, []);

  const value = useMemo<AuthCtx>(() => ({
    user, status,
    login: (e, p) => start("/auth/login", e, p),
    register: (e, p) => start("/auth/register", e, p),
    logout: async () => {
      await api("/auth/logout", { method: "POST" }).catch(() => undefined);
      setAccessToken(null); setUser(null); setStatus("anon");
    },
  }), [user, status, start]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
