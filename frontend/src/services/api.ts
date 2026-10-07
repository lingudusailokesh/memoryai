// Access token lives only in memory (not localStorage), so XSS can't steal a long-lived credential.
// The refresh token is an httpOnly cookie the browser sends automatically to /api/auth/*.
let accessToken: string | null = null;
export const setAccessToken = (t: string | null) => { accessToken = t; };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Render's free services can be asleep independently. Wait using a read-only
// database readiness probe; never retry an authentication POST automatically.
let readiness: Promise<void> | null = null;
async function checkReadiness(): Promise<void> {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch("/api/ready", {
        credentials: "include", cache: "no-store",
        signal: AbortSignal.timeout(Math.min(10_000, deadline - Date.now())),
      });
      if (r.ok && (await r.json().catch(() => null))?.status === "ready") return;
      if (!r.ok && r.status < 500 && r.status !== 429) {
        throw new ApiError(r.status, "Could not reach the server. Please try again.");
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
      // Network failures and gateway/startup responses are safe to probe again.
    }
    const remaining = deadline - Date.now();
    if (remaining > 0) await new Promise<void>((resolve) => setTimeout(resolve, Math.min(2_000, remaining)));
  }
  throw new ApiError(503, "The server is still starting or unavailable. Please try again shortly.");
}

function waitForBackend(): Promise<void> {
  readiness ??= checkReadiness().finally(() => { readiness = null; });
  return readiness;
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  if (["/auth/login", "/auth/register", "/auth/refresh"].includes(path)) await waitForBackend();
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return fetch(`/api${path}`, { ...init, headers, credentials: "include" });
}

// One shared in-flight refresh: refresh tokens are single-use, so parallel calls must not race.
let refreshing: Promise<boolean> | null = null;
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    const r = await request("/auth/refresh", { method: "POST" });
    if (!r.ok) { setAccessToken(null); return false; }
    setAccessToken(((await r.json()) as { access_token: string }).access_token);
    return true;
  })().catch(() => {
    setAccessToken(null);
    return false;
  }).finally(() => { refreshing = null; });
  return refreshing;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r = await request(path, init);
  if (r.status === 401 && !path.startsWith("/auth/") && (await refreshSession())) r = await request(path, init);
  if (!r.ok) {
    const body = (await r.json().catch(() => null)) as { detail?: unknown } | null;
    const msg = typeof body?.detail === "string" ? body.detail
      : r.status >= 500 ? "The server is unavailable. Please try again shortly."
      : "Check your details and try again.";
    throw new ApiError(r.status, msg);
  }
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}

export interface SseData {
  text?: string; message?: string; retryable?: boolean; code?: string; message_id?: string; title?: string | null; memories_used?: number;
}

/** POST and read a text/event-stream response. Resolves when the stream ends; `signal` aborts it (Stop button). */
export async function streamSse(
  path: string, init: RequestInit, signal: AbortSignal, onEvent: (name: string, data: SseData) => void,
): Promise<void> {
  const opts = { ...init, signal };
  let r = await request(path, opts);
  if (r.status === 401 && (await refreshSession())) r = await request(path, opts);
  if (!r.ok || !r.body) {
    const body = (await r.json().catch(() => null)) as { detail?: unknown } | null;
    throw new ApiError(r.status, typeof body?.detail === "string" ? body.detail : "Could not reach the server.");
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, end);
      buf = buf.slice(end + 2);
      let name = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) onEvent(name, JSON.parse(data) as SseData);
    }
  }
}
