import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BarChart3, Brain, LayoutDashboard, Menu, MessageSquare, Search, Settings, History, LogOut, X } from "lucide-react";
import Logo from "../components/Logo";
import ThemeToggle from "../components/ThemeToggle";
import { useAuth } from "../hooks/useAuth";
import { api } from "../services/api";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/memories", label: "Memories", icon: Brain },
  { to: "/conversations", label: "Conversations", icon: History },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function AppLayout() {
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ conversations: { id: string; title: string }[]; memories: { id: string; text: string }[] }>({ conversations: [], memories: [] });
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  useEffect(() => { const handler = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette(true); } if (event.key === "?" && !palette) { window.alert("Shortcuts: Ctrl/Cmd+K opens search. ? shows this help."); } }; window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler); }, [palette]);
  useEffect(() => { if (!query.trim()) { setResults({ conversations: [], memories: [] }); return; } const timer = window.setTimeout(() => { void api<typeof results>(`/search?q=${encodeURIComponent(query)}`).then(setResults).catch(() => setResults({ conversations: [], memories: [] })); }, 200); return () => window.clearTimeout(timer); }, [query]);
  return (
    <div className="min-h-screen lg:pl-60">
      <aside className={`fixed inset-y-0 left-0 z-30 flex w-60 flex-col bg-side text-white/90 transition-transform lg:translate-x-0 ${open ? "" : "-translate-x-full"}`}>
        <div className="flex items-center gap-2 px-5 py-5 text-accent"><Logo /><span className="text-lg font-semibold text-white">MemoryAI</span></div>
        <nav className="flex-1 space-y-1 px-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-white/10 text-white" : "hover:bg-white/5"}`}>
              <Icon size={18} />{label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t border-white/10 p-4 text-sm">
          <span className="truncate pr-2" title={user?.email}>{user?.email}</span>
          <div className="flex shrink-0"><ThemeToggle className="text-white" />
            <button onClick={logout} aria-label="Log out" className="rounded-lg p-2 hover:bg-white/10"><LogOut size={18} /></button></div>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-20 bg-black/40 lg:hidden" onClick={() => setOpen(false)} />}
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur">
        <button className="rounded-lg p-2 hover:bg-line/60 lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}><Menu size={20} /></button>
        <button onClick={() => setPalette(true)} className="flex max-w-md flex-1 items-center gap-2 rounded-lg border border-line bg-card px-3 py-2 text-left text-sm text-mute"><Search size={16} />Search <span className="ml-auto text-xs">Ctrl K</span></button>
        <ThemeToggle className="ml-auto" />
      </header>
      <main className="p-4 lg:p-8"><Outlet /></main>
      {palette && <div className="fixed inset-0 z-50 grid place-items-start bg-black/40 p-4 pt-24" onMouseDown={() => setPalette(false)}><div className="w-full max-w-xl rounded-xl border border-line bg-card p-3 shadow-xl" onMouseDown={(event) => event.stopPropagation()}><div className="flex items-center gap-2 border-b border-line pb-2"><Search size={18}/><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search conversations and memories" className="w-full bg-transparent py-2 outline-none"/><button onClick={() => setPalette(false)} aria-label="Close search"><X size={18}/></button></div><div className="max-h-72 overflow-y-auto pt-2 text-sm">{results.conversations.map((item) => <button key={item.id} onClick={() => { navigate(`/chat/${item.id}`); setPalette(false); }} className="block w-full rounded px-3 py-2 text-left hover:bg-bg">Chat · {item.title}</button>)}{results.memories.map((item) => <button key={item.id} onClick={() => { navigate("/memories"); setPalette(false); }} className="block w-full rounded px-3 py-2 text-left hover:bg-bg">Memory · {item.text}</button>)}{query && !results.conversations.length && !results.memories.length && <p className="p-3 text-mute">No matches.</p>} {!query && <button onClick={() => { navigate("/chat"); setPalette(false); }} className="block w-full rounded px-3 py-2 text-left hover:bg-bg">New chat</button>}</div></div></div>}
    </div>
  );
}
