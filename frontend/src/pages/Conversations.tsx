import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { api } from "../services/api";

interface Convo { id: string; title: string; updated_at: string }

export default function Conversations() {
  const [items, setItems] = useState<Convo[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Convo[]>("/conversations?limit=100").then(setItems).catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load."));
  }, []);

  async function remove(c: Convo) {
    if (!window.confirm(`Delete "${c.title}"? This removes its messages.`)) return;
    try {
      await api(`/conversations/${c.id}`, { method: "DELETE" });
      setItems((p) => (p ?? []).filter((x) => x.id !== c.id));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not delete."); }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-4 text-2xl font-semibold">Conversations</h1>
      {error && <p role="alert" className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {items === null && !error && <p className="text-mute">Loading…</p>}
      {items?.length === 0 && <p className="text-mute">No conversations yet. <Link to="/chat" className="text-accent underline">Start one</Link>.</p>}
      <ul className="space-y-2">
        {items?.map((c) => (
          <li key={c.id} className="flex items-center justify-between rounded-xl border border-line bg-card px-4 py-3">
            <Link to={`/chat/${c.id}`} className="min-w-0 flex-1">
              <p className="truncate font-medium">{c.title}</p>
              <p className="text-xs text-mute">{new Date(c.updated_at).toLocaleString()}</p>
            </Link>
            <button onClick={() => void remove(c)} aria-label={`Delete ${c.title}`} className="rounded-lg p-2 text-mute hover:bg-line/60"><Trash2 size={16} /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}
