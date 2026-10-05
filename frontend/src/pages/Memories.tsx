import { useCallback, useEffect, useState } from "react";
import { Check, History, Pencil, RotateCcw, Trash2, X } from "lucide-react";
import { api } from "../services/api";

type View = "active" | "pending" | "superseded";
interface Memory { id: string; text: string; created_at?: string | null; category?: string | null; importance?: number | null; supersedes?: string | null }
interface Version { content: string; reason: string; created_at: string }
const msg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
const REASON: Record<string, string> = { edited: "Edited", merged: "Merged with a duplicate", superseded: "Replaced by a newer memory", restored: "Restored" };

export default function Memories() {
  const [view, setView] = useState<View>("active");
  const [items, setItems] = useState<Memory[] | null>(null);
  const [counts, setCounts] = useState({ pending: 0, superseded: 0 });
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [history, setHistory] = useState<{ id: string; versions: Version[] } | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [typed, setTyped] = useState("");
  const [provider, setProvider] = useState("");
  const [mode, setMode] = useState<"auto" | "ask">("auto");
  const custom = provider === "custom";

  const load = useCallback(async (v: View, q: string) => {
    try {
      setError("");
      const params = new URLSearchParams({ status: v });
      if (q && v === "active") params.set("q", q);
      setItems(await api<Memory[]>(`/memories?${params}`));
    } catch (e) { setError(msg(e, "Could not load memories.")); }
  }, []);
  const loadCounts = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([api<Memory[]>("/memories?status=pending"), api<Memory[]>("/memories?status=superseded")]);
      setCounts({ pending: p.length, superseded: s.length });
    } catch { /* badges are optional */ }
  }, []);

  useEffect(() => { // debounced: search as you type without a request per keystroke
    const t = setTimeout(() => void load(view, query.trim()), 300);
    return () => clearTimeout(t);
  }, [view, query, load]);
  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then((d: { memory_provider?: string }) => setProvider(d.memory_provider ?? "")).catch(() => undefined);
    api<{ memory_mode?: "auto" | "ask" }>("/me").then((u) => setMode(u.memory_mode ?? "auto")).catch(() => undefined);
  }, []);
  useEffect(() => { if (custom) void loadCounts(); }, [custom, loadCounts]);

  const drop = (id: string) => setItems((p) => (p ?? []).filter((x) => x.id !== id));
  async function run(fn: () => Promise<void>, fallback: string) {
    try { await fn(); await loadCounts(); } catch (e) { setError(msg(e, fallback)); }
  }
  const save = () => editing && editing.text.trim() && run(async () => {
    const m = await api<Memory>(`/memories/${editing.id}`, { method: "PATCH", body: JSON.stringify({ text: editing.text }) });
    setItems((p) => (p ?? []).map((x) => (x.id === m.id ? m : x)));
    setEditing(null);
  }, "Could not save.");
  const remove = (m: Memory) => window.confirm(`Delete this memory?\n\n"${m.text}"`) && run(async () => {
    await api(`/memories/${m.id}`, { method: "DELETE" }); drop(m.id);
  }, "Could not delete.");
  const approve = (m: Memory) => run(async () => { await api(`/memories/${m.id}/approve`, { method: "POST" }); drop(m.id); }, "Could not approve.");
  const reject = (m: Memory) => run(async () => { await api(`/memories/${m.id}/reject`, { method: "POST" }); drop(m.id); }, "Could not reject.");
  const restore = (m: Memory) => run(async () => { await api(`/memories/${m.id}/restore`, { method: "POST" }); drop(m.id); }, "Could not restore.");
  const removeAll = () => run(async () => {
    await api("/memories/delete-all", { method: "POST", body: JSON.stringify({ confirm: typed }) });
    setItems([]); setConfirmAll(false); setTyped("");
  }, "Could not delete.");
  const changeMode = (next: "auto" | "ask") => run(async () => {
    await api("/me/settings", { method: "PATCH", body: JSON.stringify({ memory_mode: next }) }); setMode(next);
  }, "Could not change the setting.");
  const toggleHistory = (m: Memory) => run(async () => {
    if (history?.id === m.id) { setHistory(null); return; }
    setHistory({ id: m.id, versions: await api<Version[]>(`/memories/${m.id}/versions`) });
  }, "Could not load history.");

  const tab = (v: View, label: string, n = 0) => (
    <button key={v} onClick={() => { setView(v); setEditing(null); setHistory(null); }} aria-pressed={view === v}
      className={`rounded-lg px-3 py-1.5 text-sm ${view === v ? "bg-accent text-accent-ink" : "border border-line hover:bg-line/50"}`}>
      {label}{n > 0 && <span className="ml-1.5 rounded-full bg-black/15 px-1.5 text-xs">{n}</span>}
    </button>
  );
  const iconBtn = "rounded-lg p-2 text-mute hover:bg-line/60";

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Memories</h1>
        <button onClick={() => setConfirmAll((v) => !v)} disabled={!items?.length}
          className="rounded-lg border border-red-500/50 px-3 py-1.5 text-sm text-red-700 disabled:opacity-40 dark:text-red-400">Delete all</button>
      </div>
      <p className="mb-3 text-sm text-mute">Facts MemoryAI remembers about you. Edit or delete anything; deleted memories also disappear from "Used memories" lists in your chats. Passwords, keys and ID numbers are never stored.</p>
      {provider === "fake" && <p className="mb-3 rounded-lg border border-amber-500/50 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">Offline test mode: memories live in server memory and are lost on restart. Search matches shared words only.</p>}
      {custom && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <div className="flex gap-2">{tab("active", "Memories")}{tab("pending", "Suggested", counts.pending)}{tab("superseded", "Replaced", counts.superseded)}</div>
          <label className="ml-auto flex items-center gap-2 text-sm">New memories:
            <select value={mode} onChange={(e) => void changeMode(e.target.value as "auto" | "ask")} className="rounded-lg border border-line bg-card px-2 py-1">
              <option value="auto">Save automatically</option><option value="ask">Ask me first</option>
            </select>
          </label>
        </div>
      )}
      {confirmAll && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-red-500/50 p-3 text-sm">
          <span>This permanently deletes every memory, including suggestions and replaced ones. Type <b>DELETE</b> to confirm.</span>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Type DELETE to confirm" className="rounded-lg border border-line bg-card px-2 py-1" />
          <button onClick={() => void removeAll()} disabled={typed !== "DELETE"} className="rounded-lg bg-red-600 px-3 py-1 text-white disabled:opacity-40">Delete everything</button>
          <button onClick={() => { setConfirmAll(false); setTyped(""); }} className="underline">Cancel</button>
        </div>
      )}
      {view === "active" && <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search memories" aria-label="Search memories"
        className="mb-4 w-full rounded-lg border border-line bg-card px-3 py-2" />}
      {view === "pending" && <p className="mb-3 text-sm text-mute">New facts wait here until you approve them. Approving one that contradicts an older memory replaces the older one (you can restore it later).</p>}
      {view === "superseded" && <p className="mb-3 text-sm text-mute">Older memories that a newer one replaced. They are never used in chats. Restore one to bring it back (the newer one then becomes the replaced one).</p>}
      {error && <p role="alert" className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {items === null && !error && <p className="text-mute">Loading…</p>}
      {items?.length === 0 && <p className="text-mute">{view === "pending" ? "Nothing waiting for review." : view === "superseded" ? "Nothing has been replaced." : query ? "No memories match your search." : "Nothing remembered yet. Tell MemoryAI about yourself in a chat."}</p>}
      <ul className="space-y-2">
        {items?.map((m) => (
          <li key={m.id} className="rounded-xl border border-line bg-card px-4 py-3">
            {editing?.id === m.id ? (
              <div className="space-y-2">
                <textarea value={editing.text} onChange={(e) => setEditing({ id: m.id, text: e.target.value })} maxLength={500} rows={2}
                  aria-label="Edit memory" className="w-full resize-none rounded-lg border border-line bg-bg px-3 py-2" />
                <div className="flex gap-2 text-sm">
                  <button onClick={() => void save()} disabled={!editing.text.trim()} className="rounded-lg bg-accent px-3 py-1 text-accent-ink disabled:opacity-50">Save</button>
                  <button onClick={() => setEditing(null)} className="underline">Cancel</button>
                </div>
              </div>
            ) : (
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="whitespace-pre-wrap break-words">{m.text}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-mute">
                    {m.category && <span className="rounded-full border border-line px-2 py-0.5">{m.category}</span>}
                    {typeof m.importance === "number" && <span title="Importance assigned when this was saved">importance {m.importance.toFixed(1)}</span>}
                    {m.created_at && <span>{new Date(m.created_at).toLocaleDateString()}</span>}
                    {m.supersedes && <span className="text-amber-700 dark:text-amber-400">would replace an older memory</span>}
                  </p>
                </div>
                <div className="flex shrink-0">
                  {view === "pending" && <>
                    <button onClick={() => void approve(m)} aria-label="Approve suggestion" className={iconBtn}><Check size={16} /></button>
                    <button onClick={() => void reject(m)} aria-label="Reject suggestion" className={iconBtn}><X size={16} /></button></>}
                  {view === "superseded" && <button onClick={() => void restore(m)} aria-label="Restore memory" title="Restore" className={iconBtn}><RotateCcw size={16} /></button>}
                  {custom && <button onClick={() => void toggleHistory(m)} aria-label="Show history" aria-expanded={history?.id === m.id} className={iconBtn}><History size={16} /></button>}
                  {view !== "superseded" && <button onClick={() => setEditing({ id: m.id, text: m.text })} aria-label="Edit memory" className={iconBtn}><Pencil size={16} /></button>}
                  {view !== "pending" && <button onClick={() => void remove(m)} aria-label="Delete memory" className={iconBtn}><Trash2 size={16} /></button>}
                </div>
              </div>
            )}
            {history?.id === m.id && (
              <ul className="mt-2 space-y-1 rounded-lg border border-line bg-bg p-2 text-xs text-mute">
                {history.versions.length === 0 && <li>No earlier versions: this memory has never changed.</li>}
                {history.versions.map((v, i) => <li key={i}><b>{REASON[v.reason] ?? v.reason}</b> · {new Date(v.created_at).toLocaleString()}<br />"{v.content}"</li>)}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
