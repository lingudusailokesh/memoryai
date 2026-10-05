import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../services/api";

// MOCK DATA: replaced by /api/dashboard/summary in Stage 9.
interface Summary { stats: { conversations: number; memories: number; messages: number; retrieval_rate: number }; activity: { date: string; messages: number }[]; recent_memories: { id: string; text: string; category: string; importance: number }[] }

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [focus, setFocus] = useState("Loading your focus…");
  useEffect(() => { void api<Summary>("/dashboard/summary").then(setSummary).catch(() => setSummary(null)); void api<{ text: string }>("/dashboard/focus").then((value) => setFocus(value.text)).catch(() => setFocus("Your focus suggestion is unavailable right now.")); }, []);
  const stats = summary ? [
    { label: "Total conversations", value: summary.stats.conversations, grad: "from-teal-600 to-emerald-500" },
    { label: "Memories stored", value: summary.stats.memories, grad: "from-indigo-600 to-sky-500" },
    { label: "Messages", value: summary.stats.messages, grad: "from-amber-600 to-orange-500" },
    { label: "Memory retrieval rate", value: `${summary.stats.retrieval_rate}%`, grad: "from-rose-600 to-fuchsia-500" },
  ] : [];
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        {!summary && <span className="rounded-full border border-amber-500/50 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400">Loading data</span>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className={`rounded-xl bg-gradient-to-br ${s.grad} p-5 text-white shadow-sm`}>
            <p className="text-sm text-white/85">{s.label}</p><p className="mt-2 text-3xl font-semibold">{s.value}</p>
          </div>
        ))}
      </div>
      <section className="rounded-xl border border-line bg-card p-5"><h2 className="font-medium">Today's focus</h2><p className="mt-2 text-sm text-mute">{focus}</p></section>
      <section className="rounded-xl border border-line bg-card p-5">
        <h2 className="mb-4 font-medium">Conversation activity</h2>
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={summary?.activity ?? []}>
              <CartesianGrid vertical={false} stroke="rgb(var(--line))" />
              <XAxis dataKey="date" stroke="rgb(var(--mute))" /><YAxis stroke="rgb(var(--mute))" />
              <Tooltip contentStyle={{ background: "rgb(var(--card))", border: "1px solid rgb(var(--line))", color: "rgb(var(--ink))" }} />
              <Bar dataKey="messages" fill="rgb(var(--accent))" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
      <section className="rounded-xl border border-line bg-card p-5"><h2 className="font-medium">Recent memories</h2><div className="mt-3 space-y-2 text-sm">{summary?.recent_memories.length ? summary.recent_memories.map((memory) => <div key={memory.id} className="flex justify-between gap-3 border-t border-line pt-2"><span>{memory.text}</span><span className="shrink-0 text-mute">{memory.category} · {Math.round(memory.importance * 100)}%</span></div>) : <p className="text-mute">No memories yet.</p>}</div></section>
    </div>
  );
}
