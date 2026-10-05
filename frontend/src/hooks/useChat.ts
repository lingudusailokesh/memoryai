import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, streamSse } from "../services/api";

export interface ChatMessage { id: string; role: "user" | "assistant"; content: string; memories_used_count?: number }
interface Convo { id: string; title: string; memory_enabled: boolean }
export interface ChatError { message: string; retryable: boolean }
const DEFAULT_TITLE = "New conversation";

export function useChat(routeId: string | undefined) {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [title, setTitle] = useState(DEFAULT_TITLE);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const idRef = useRef<string | undefined>(routeId);
  const createdRef = useRef<string | undefined>(undefined); // conversation we just made: don't reload it mid-stream
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (routeId && routeId === createdRef.current) return;
    createdRef.current = undefined;
    abortRef.current?.abort();
    idRef.current = routeId;
    setError(null);
    if (!routeId) { setMessages([]); setTitle(DEFAULT_TITLE); setMemoryEnabled(true); return; }
    let alive = true;
    setLoading(true);
    Promise.all([api<Convo>(`/conversations/${routeId}`), api<ChatMessage[]>(`/conversations/${routeId}/messages`)])
      .then(([c, m]) => { if (alive) { setTitle(c.title); setMemoryEnabled(c.memory_enabled); setMessages(m); } })
      .catch((e: unknown) => { if (alive) setError({ message: e instanceof Error ? e.message : "Could not load.", retryable: false }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [routeId]);

  const run = useCallback(async (path: string, optimisticUser?: string) => {
    setError(null);
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const draft = `draft-${Date.now()}`;
    setMessages((p) => [
      ...p,
      ...(optimisticUser ? [{ id: `u-${draft}`, role: "user" as const, content: optimisticUser }] : []),
      { id: draft, role: "assistant", content: "" },
    ]);
    let finished = false;
    try {
      await streamSse(path, { method: "POST", body: optimisticUser ? JSON.stringify({ content: optimisticUser }) : undefined },
        ctrl.signal, (name, d) => {
          if (name === "token") setMessages((p) => p.map((m) => (m.id === draft ? { ...m, content: m.content + (d.text ?? "") } : m)));
          else if (name === "done") {
            finished = true;
            setMessages((p) => p.map((m) => (m.id === draft ? { ...m, id: d.message_id ?? m.id, memories_used_count: d.memories_used ?? 0 } : m)));
            if (d.title) setTitle(d.title);
          } else if (name === "error") {
            finished = true;
            setError({ message: d.message ?? "Something went wrong.", retryable: d.retryable ?? true });
          }
        });
      if (!finished) setError({ message: "The connection dropped before the reply finished.", retryable: true });
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError"))
        setError({ message: e instanceof Error ? e.message : "Connection lost.", retryable: true });
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setMessages((p) => p.filter((m) => !(m.id === draft && m.content === "")));
    }
  }, []);

  const send = useCallback(async (text: string) => {
    if (streaming || !text.trim()) return;
    let id = idRef.current;
    if (!id) {
      try {
        const c = await api<Convo>("/conversations", { method: "POST", body: JSON.stringify({ memory_enabled: memoryEnabled }) });
        id = c.id; idRef.current = id; createdRef.current = id;
        navigate(`/chat/${id}`, { replace: true });
      } catch (e) {
        setError({ message: e instanceof Error ? e.message : "Could not start a conversation.", retryable: false });
        return;
      }
    }
    await run(`/conversations/${id}/messages`, text.trim());
  }, [streaming, navigate, run, memoryEnabled]);

  /** Regenerate the last reply, or retry after an error. Re-reads the server's latest message id first,
   *  because a stopped reply is saved by the server and our local copy may not know its id. */
  const regenerate = useCallback(async () => {
    const id = idRef.current;
    if (!id || streaming) return;
    try {
      const list = await api<ChatMessage[]>(`/conversations/${id}/messages`);
      const last = list[list.length - 1];
      if (!last) return;
      setMessages(last.role === "assistant" ? list.slice(0, -1) : list);
      await run(`/conversations/${id}/messages/${last.id}/regenerate`);
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : "Could not retry.", retryable: true });
    }
  }, [streaming, run]);

  /** The server enforces this per conversation. Before the chat exists we just remember the choice for creation. */
  const toggleMemory = useCallback(async () => {
    const next = !memoryEnabled;
    const id = idRef.current;
    if (!id) { setMemoryEnabled(next); return; }
    try {
      await api(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ memory_enabled: next }) });
      setMemoryEnabled(next);
    } catch (e) { setError({ message: e instanceof Error ? e.message : "Could not change the memory setting.", retryable: false }); }
  }, [memoryEnabled]);

  const stop = useCallback(() => abortRef.current?.abort(), []);
  return { messages, title, loading, streaming, error, memoryEnabled, send, stop, regenerate, toggleMemory };
}
