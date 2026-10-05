import { useState } from "react";
import { Brain } from "lucide-react";
import { api } from "../services/api";

interface Used { id: string; text: string }

/** "Used N memories" chip: click to see exactly which memories shaped this reply. */
export default function MemoriesUsed({ messageId, count }: { messageId: string; count: number }) {
  const [items, setItems] = useState<Used[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(false);
  if (count < 1 || messageId.startsWith("draft-")) return null;

  async function toggle() {
    setOpen((o) => !o);
    if (items === null) {
      try { setItems(await api<Used[]>(`/messages/${messageId}/memories-used`)); } catch { setError(true); }
    }
  }
  return (
    <div className="mt-2 text-xs">
      <button onClick={() => void toggle()} aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-mute hover:bg-line/50">
        <Brain size={12} />Used {count} {count === 1 ? "memory" : "memories"}
      </button>
      {open && (
        <ul className="mt-1 space-y-1 rounded-lg border border-line bg-bg p-2 text-mute">
          {error && <li>Could not load memories.</li>}
          {items === null && !error && <li>Loading…</li>}
          {items?.map((m) => <li key={m.id}>• {m.text}</li>)}
        </ul>
      )}
    </div>
  );
}
