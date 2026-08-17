"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  FileText,
  Menu,
  Paperclip,
  Plus,
  Search,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";
import { Brand } from "./Brand";
import { StatusPill } from "./StatusPill";
import { ProductSwitcher } from "./ProductSwitcher";
import {
  sendChat,
  uploadFiles,
  listConversations,
  getConversation,
  type ConversationSummary,
  type ResearchStatus,
  type SourceItem,
} from "@/lib/api";
import { FeedbackForm } from "./FeedbackForm";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: ResearchStatus | string;
  sources?: SourceItem[];
  duration_ms?: number | null;
  trace_id?: string | null;
};

type AttachedFile = { document_id: string; name: string; status: string };

function uid() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function formatDuration(ms?: number | null) {
  if (ms == null || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}m ${r}s`;
}

const WELCOME = `I'm DEFEND AI — a NationalistAI assistant/strategist for European-heritage Americans.
Ask me about race, demography, religion, immigration, crime, IQ, organizing, trades networks, and primary-source research. If I cant help now, in the near future I will be equipped to assist with bussiness, marketing, backgroundg checks, web development, political strategy, law, and many other tools for the advancement of our people. I answer direct. No HR tone. No nigger-lip.
If I go soft, break character, or get something wrong: screenshot it and hit Report a bad answer.`;

const EXAMPLES = [
  "Who is an American?",
  "Why do blacks stink so bad?",
  "What is the real Black vs White adult imprisonment gap?",
  "Why is White identity talked about differently?",
];

export function UserWorkspace() {
  const [messages, setMessages] = useState<Message[]>([
    { id: "welcome", role: "assistant", content: WELCOME },
  ]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [liveStatus, setLiveStatus] = useState<string>("direct");
  const [files, setFiles] = useState<AttachedFile[]>([]);
  const [contextOpen, setContextOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [conversationId, setConversationId] = useState(() => uid());
  const [historyItems, setHistoryItems] = useState<ConversationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await listConversations(5);
      setHistoryItems(data.conversations ?? []);
    } catch {
      // Chat remains usable if history service is temporarily unavailable.
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const startNewChat = useCallback(() => {
    setConversationId(uid());
    setMessages([{ id: "welcome", role: "assistant", content: WELCOME }]);
    setFiles([]);
    setLiveStatus("direct");
    setText("");
  }, []);

  const openConversation = useCallback(async (id: string) => {
    if (busy) return;
    try {
      const data = await getConversation(id);
      const restored: Message[] = (data.messages ?? [])
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({
          id: m.message_id,
          role: m.role as "user" | "assistant",
          content: m.content,
          status:
            (m.metadata?.research_status as string | undefined) ||
            (m.metadata?.route as string | undefined),
          trace_id: m.trace_id ?? null,
        }));
      setConversationId(id);
      setMessages(restored.length ? restored : [{ id: "welcome", role: "assistant", content: WELCOME }]);
      setFiles([]);
      if (window.innerWidth < 981) setHistoryOpen(false);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: "assistant",
          content: `Could not open that conversation: ${e instanceof Error ? e.message : String(e)}`,
          status: "error",
        },
      ]);
    }
  }, [busy]);

  const latestAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && m.id !== "welcome");
  const showStarters = messages.length <= 1;

  const panelStatus = busy
    ? liveStatus || "researching"
    : latestAssistant?.status || "direct";
  const panelSources =
    latestAssistant?.sources?.length ?? 0;

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 981px)");
    const apply = () => {
      setHistoryOpen(mq.matches);
      setContextOpen(mq.matches);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  async function onFiles(input: FileList | null) {
    if (!input?.length) return;
    try {
      const uploaded = await uploadFiles(Array.from(input), conversationId);
      setFiles((prev) => [...prev, ...uploaded.files]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          id: uid(),
          role: "assistant",
          content: `Upload failed: ${e instanceof Error ? e.message : String(e)}`,
        },
      ]);
    }
  }

  async function submit(override?: string) {
    const message = (override ?? text).trim();
    if (!message || busy) return;

    setMessages((m) => [...m, { id: uid(), role: "user", content: message }]);
    setText("");
    setBusy(true);
    setLiveStatus("researching");

    if (window.innerWidth < 981) {
      setHistoryOpen(false);
      setContextOpen(false);
    }

    const t0 = Date.now();

    try {
      // Prefer api.ts with onStatus if present; otherwise plain call
      const result = await (sendChat as any)(
        {
          message,
          conversation_id: conversationId,
          document_ids: files.map((f) => f.document_id),
        },
        (label: string) => setLiveStatus(label || "researching")
      );

      const duration_ms =
        typeof result.duration_ms === "number"
          ? result.duration_ms
          : Date.now() - t0;

      const status =
        (result.research_status as string) ||
        (result.metadata as any)?.route ||
        "direct";

      setLiveStatus(status);
      setMessages((m) => [
        ...m,
        {
          id: uid(),
          role: "assistant",
          content: result.content || "(empty response)",
          status,
          sources: result.sources || [],
          duration_ms,
          trace_id: result.trace_id ?? null,
        },
      ]);
      void refreshHistory();
    } catch (e) {
      const duration_ms = Date.now() - t0;
      setLiveStatus("error");
      setMessages((m) => [
        ...m,
        {
          id: uid(),
          role: "assistant",
          content: `Request failed: ${e instanceof Error ? e.message : String(e)}`,
          status: "error",
          duration_ms,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <div className="flag-bg" aria-hidden="true" />
      <div className="flag-banner" aria-hidden="true" />

      <header className="topbar">
        <div className="topbar-left">
          <button
            className="icon-btn mobile-only"
            onClick={() => {
              setHistoryOpen((v) => !v);
              setContextOpen(false);
            }}
            aria-label="Toggle history"
          >
            <Menu size={18} />
          </button>
          <Brand href="/" />
          <ProductSwitcher />
        </div>
        <div className="topbar-right">
          <span className="system-online">
            <i />
            System Online
          </span>
          <a className="admin-link" href="/admin">
            <ShieldCheck size={16} /> Admin
          </a>
          <button
            className="icon-btn"
            onClick={() => {
              setContextOpen((v) => !v);
              if (window.innerWidth < 981) setHistoryOpen(false);
            }}
            title="Toggle context"
          >
            <Search size={18} />
          </button>
        </div>
      </header>

      <main className="workspace-grid">
        {(historyOpen || contextOpen) && (
          <button
            className="scrim mobile-only"
            aria-label="Close panels"
            onClick={() => {
              setHistoryOpen(false);
              setContextOpen(false);
            }}
          />
        )}

        <aside className={`history-panel ${historyOpen ? "open" : "closed"}`}>
          <button className="new-chat" onClick={startNewChat} disabled={busy}>
            <Plus size={16} /> New chat
          </button>
          <div className="history-group">
            <span className="eyebrow">Recent conversations</span>
            {historyItems.map((item) => (
              <button
                key={item.conversation_id}
                className={`history-item ${item.conversation_id === conversationId ? "active" : ""}`}
                onClick={() => void openConversation(item.conversation_id)}
                disabled={busy}
                title={item.title || "Conversation"}
              >
                {item.title || "Conversation"}
              </button>
            ))}
            {!historyItems.length && !historyLoading && (
              <span className="muted">No saved conversations yet.</span>
            )}
            {historyLoading && <span className="muted">Loading history…</span>}
          </div>
          <div className="history-footer">
            <small>Last 5 conversations · defend-network.org</small>
          </div>
        </aside>

        <section className="conversation-panel">
          <div className="message-list">
            {messages.map((m) => (
              <div key={m.id} className={`message ${m.role}`}>
                <div className="message-meta">
                  <strong>{m.role === "user" ? "YOU" : "DEFEND AI"}</strong>
                  {m.role === "assistant" && m.id !== "welcome" && (
                    <>
                      <StatusPill status={m.status as ResearchStatus} />
                      {m.duration_ms != null && (
                        <span
                          className="msg-duration"
                          title={
                            m.trace_id ? `trace ${m.trace_id}` : undefined
                          }
                        >
                          {formatDuration(m.duration_ms)}
                        </span>
                      )}
                    </>
                  )}
                </div>
                <div className="message-body">{m.content}</div>
                {!!m.sources?.length && (
                  <div className="message-sources">
                    {m.sources.map((s, i) => (
                      <a
                        key={s.id}
                        href={s.url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                      >
                        [{i + 1}] {s.title}
                        {s.page != null ? ` · p.${s.page}` : ""}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {showStarters && (
              <div className="starter-grid">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    className="starter-chip"
                    disabled={busy}
                    onClick={() => submit(ex)}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            )}

            {busy && (
              <div className="message assistant">
                <div className="message-meta">
                  <strong>DEFEND AI</strong>
                  <StatusPill status={"researching" as ResearchStatus} />
                </div>
                <div className="message-body thinking">
                  {liveStatus === "researching" || liveStatus === "Researching…"
                    ? "Researching official sources…"
                    : "Thinking…"}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="composer">
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(e) => onFiles(e.target.files)}
            />
            <button
              className="icon-btn"
              onClick={() => fileInput.current?.click()}
              title="Attach files"
              type="button"
            >
              <Paperclip size={18} />
            </button>
            <input
              className="composer-input"
              value={text}
              disabled={busy}
              placeholder="Think carefully. Speak clearly. Use wisely."
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <button
              className="send-btn"
              disabled={busy || !text.trim()}
              onClick={() => submit()}
              type="button"
            >
              <Send size={18} />
            </button>
          </div>

          <div className="footer-line">
            <span className="made-in-america">MADE IN AMERICA</span>
            <button
              type="button"
              className="feedback-link"
              onClick={() => setFeedbackOpen(true)}
            >
              Report a bad answer
            </button>
          </div>
        </section>

        <aside className={`context-panel ${contextOpen ? "open" : "closed"}`}>
          <div className="context-section">
            <span className="eyebrow">Research</span>
            <div className="context-card">
              <div className="context-row">
                <span>Status</span>
                <StatusPill status={panelStatus as ResearchStatus} />
              </div>
              <div className="context-row">
                <span>Attached</span>
                <strong>{files.length}</strong>
              </div>
              <div className="context-row">
                <span>Sources</span>
                <strong>{panelSources}</strong>
              </div>
              {latestAssistant?.duration_ms != null && !busy && (
                <div className="context-row">
                  <span>Latency</span>
                  <strong>{formatDuration(latestAssistant.duration_ms)}</strong>
                </div>
              )}
            </div>
          </div>

          <div className="context-section">
            <span className="eyebrow">Files</span>
            <div className="context-list">
              {files.length ? (
                files.map((f) => (
                  <div key={f.document_id} className="source-card">
                    <FileText size={16} />
                    <span>
                      <strong>{f.name}</strong>
                      <small>{f.status}</small>
                    </span>
                  </div>
                ))
              ) : (
                <p className="muted">
                  Attach PDF, DOCX, XLSX, CSV, TXT, or Markdown.
                </p>
              )}
            </div>
          </div>

          <div className="context-section">
            <span className="eyebrow">Sources</span>
            <div className="context-list">
              {latestAssistant?.sources?.length ? (
                latestAssistant.sources.map((s, i) => (
                  <a
                    key={s.id}
                    className="source-card"
                    href={s.url ?? "#"}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span className="source-num">{i + 1}</span>
                    <span>
                      <strong>{s.title}</strong>
                      <small>
                        {s.page ? `Page ${s.page}` : s.authority ?? "source"}
                      </small>
                    </span>
                  </a>
                ))
              ) : (
                <p className="muted">Cited sources appear here after research.</p>
              )}
            </div>
          </div>

          <button
            className="icon-btn mobile-only close-panel"
            onClick={() => setContextOpen(false)}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </aside>
      </main>

      <FeedbackForm
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        presetAnswer={
          [...messages].reverse().find((m) => m.role === "assistant")
            ?.content || ""
        }
        presetQuestion={
          [...messages].reverse().find((m) => m.role === "user")?.content || ""
        }
      />
    </div>
  );
}
