// Access token lives only in memory (not localStorage), so XSS can't steal a long-lived credential.
// The refresh token is an httpOnly cookie the browser sends automatically to /api/auth/*.
let accessToken: string | null = null;
export const setAccessToken = (t: string | null) => { accessToken = t; };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function request(path: string, init: RequestInit = {}): Promise<Response> {
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
  })().finally(() => { refreshing = null; });
  return refreshing;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r = await request(path, init);
  if (r.status === 401 && !path.startsWith("/auth/") && (await refreshSession())) r = await request(path, init);
  if (!r.ok) {
    const body = (await r.json().catch(() => null)) as { detail?: unknown } | null;
    const msg = typeof body?.detail === "string" ? body.detail : "Check your details and try again.";
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
