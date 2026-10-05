import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { RefreshCw, Send, Square } from "lucide-react";
import MemoriesUsed from "../components/MemoriesUsed";
import { useChat } from "../hooks/useChat";

export default function Chat() {
  const { id } = useParams();
  const { messages, title, loading, streaming, error, memoryEnabled, send, stop, regenerate, toggleMemory } = useChat(id);
  const [text, setText] = useState("");
  const [provider, setProvider] = useState("");
  const [memoryProvider, setMemoryProvider] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then((d: { llm_provider?: string; memory_provider?: string }) => { setProvider(d.llm_provider ?? ""); setMemoryProvider(d.memory_provider ?? ""); }).catch(() => undefined);
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [messages]);

  function submit() {
    if (!text.trim() || streaming) return;
    void send(text);
    setText("");
  }
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  }

  const last = messages[messages.length - 1];
  const canRetry = !streaming && !!id && (error?.retryable || last?.role === "assistant");
  return (
    <div className="mx-auto flex h-[calc(100vh-9rem)] max-w-3xl flex-col">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h1 className="truncate text-lg font-semibold">{title}</h1>
        <div className="flex shrink-0 items-center gap-2">
          <button role="switch" aria-checked={memoryEnabled} onClick={() => void toggleMemory()} disabled={streaming}
            title="When off, this conversation neither uses nor saves memories"
            className={`rounded-lg border px-3 py-1.5 text-sm ${memoryEnabled ? "border-accent text-accent" : "border-line text-mute"}`}>
            Memory: {memoryEnabled ? "On" : "Off"}
          </button>
          <Link to="/chat" className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-line/50">New chat</Link>
        </div>
      </div>
      {provider === "fake" && (
        <p className="mb-3 rounded-lg border border-amber-500/50 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          Offline test mode: replies are echoes from a fake provider, not a real AI. Set LLM_PROVIDER in backend/.env to use Gemini or Ollama.
        </p>
      )}
      {memoryProvider === "fake" && (
        <p className="mb-3 rounded-lg border border-amber-500/50 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          Memory is in offline test mode: it keeps sentences starting with "I " in server memory and matches by shared words. It is lost on restart.
        </p>
      )}
      <div className="flex-1 space-y-3 overflow-y-auto" aria-live="polite">
        {loading && <p className="text-mute">Loading conversation…</p>}
        {!loading && messages.length === 0 && <p className="text-mute">Say something. Your first message starts the conversation.</p>}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user"
            ? "ml-auto max-w-[80%] whitespace-pre-wrap rounded-2xl bg-accent px-4 py-2 text-accent-ink"
            : "max-w-[85%] rounded-2xl border border-line bg-card px-4 py-2"}>
            {m.role === "assistant"
              ? <div className="space-y-2 [&_a]:text-accent [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-bg [&_pre]:p-3 [&_code]:text-sm">
                  <ReactMarkdown>{m.content || "…"}</ReactMarkdown>
                  <MemoriesUsed messageId={m.id} count={m.memories_used_count ?? 0} /></div>
              : m.content}
          </div>
        ))}
        {error && (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-red-500/50 px-3 py-2 text-sm text-red-700 dark:text-red-400">
            <span>{error.message}</span>
            {canRetry && error.retryable && <button onClick={() => void regenerate()} className="shrink-0 underline">Retry</button>}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="mt-3 flex items-end gap-2">
        <textarea value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={2} maxLength={8000}
          placeholder="Message MemoryAI (Enter to send, Shift+Enter for a new line)" aria-label="Message"
          className="flex-1 resize-none rounded-lg border border-line bg-card px-3 py-2" />
        {canRetry && !error && (
          <button onClick={() => void regenerate()} aria-label="Regenerate reply" className="rounded-lg border border-line p-2 hover:bg-line/50"><RefreshCw size={18} /></button>
        )}
        {streaming
          ? <button onClick={stop} aria-label="Stop generating" className="rounded-lg bg-red-600 p-2 text-white"><Square size={18} /></button>
          : <button onClick={submit} disabled={!text.trim()} aria-label="Send" className="rounded-lg bg-accent p-2 text-accent-ink disabled:opacity-50"><Send size={18} /></button>}
      </div>
    </div>
  );
}
