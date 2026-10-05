import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../services/api";

interface Metrics { messages: { date: string; value: number }[]; memories: { date: string; value: number }[]; average_latency_ms: number; tokens_in: number; tokens_out: number }

export default function Analytics() {
  const [days, setDays] = useState(30); const [data, setData] = useState<Metrics | null>(null);
  useEffect(() => { void api<Metrics>(`/analytics?days=${days}`).then(setData).catch(() => setData(null)); }, [days]);
  return <div className="space-y-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold">Analytics</h1><p className="mt-1 text-sm text-mute">Real activity from your account.</p></div><select value={days} onChange={(event) => setDays(Number(event.target.value))} className="rounded-lg border border-line bg-card px-3 py-2 text-sm"><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select></div><div className="grid gap-4 sm:grid-cols-3">{[["Average response", `${data?.average_latency_ms ?? 0} ms`], ["Input tokens", data?.tokens_in ?? 0], ["Output tokens", data?.tokens_out ?? 0]].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-line bg-card p-5"><p className="text-sm text-mute">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></div>)}</div><section className="rounded-xl border border-line bg-card p-5"><h2 className="mb-4 font-medium">Messages per day</h2><div className="h-72"><ResponsiveContainer><BarChart data={data?.messages ?? []}><CartesianGrid vertical={false} stroke="rgb(var(--line))"/><XAxis dataKey="date" stroke="rgb(var(--mute))"/><YAxis stroke="rgb(var(--mute))"/><Tooltip contentStyle={{ background: "rgb(var(--card))", border: "1px solid rgb(var(--line))", color: "rgb(var(--ink))" }}/><Bar dataKey="value" fill="rgb(var(--accent))" radius={[5,5,0,0]}/></BarChart></ResponsiveContainer></div></section></div>;
}
