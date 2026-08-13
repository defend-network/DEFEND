"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BadgeCheck,
  Bot,
  Database,
  FileSearch,
  FileText,
  Gauge,
  Search,
  Settings,
  Shield,
  SlidersHorizontal,
  Users,
  Wrench,
} from "lucide-react";
import { Brand } from "./Brand";
import { adminDocuments, adminHealth, adminLogout, adminResearch } from "@/lib/api";
import AdminLogin from "./AdminLogin";
import TableTennisPanel from "./TableTennisPanel";
import {
  AdminSession,
  clearAdminSession,
  isOwner,
  loadAdminSession,
} from "@/lib/adminAuth";
import { UsersRolesPanel } from "./admin/identity/UsersRolesPanel";
import { KnowledgeRagPanel } from "./admin/KnowledgeRagPanel";
import { BackgroundCheckPanel } from "./admin/BackgroundCheckPanel";

type View =
  | "overview"
  | "knowledge"
  | "background"
  | "documents"
  | "research"
  | "models"
  | "tools"
  | "policy"
  | "users"
  | "audit"
  | "settings"
  | "tabletennis";

const baseItems: Array<{ id: View; label: string; icon: any }> = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "knowledge", label: "Knowledge / RAG", icon: Database },
  { id: "background", label: "Background Check", icon: BadgeCheck },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "research", label: "Research Lab", icon: FileSearch },
  { id: "models", label: "Models", icon: Bot },
  { id: "tools", label: "Tools", icon: Wrench },
  { id: "policy", label: "Policy", icon: Shield },
  { id: "users", label: "Users & Roles", icon: Users },
  { id: "audit", label: "Audit / Traces", icon: Activity },
  { id: "settings", label: "Settings", icon: Settings },
];

export function AdminWorkstation() {
  const [session, setSession] = useState<AdminSession | null>(null);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [health, setHealth] = useState<any>(null);
  const [docs, setDocs] = useState<any[]>([]);
  const [question, setQuestion] = useState("");
  const [research, setResearch] = useState<any>(null);
  const [researchBusy, setResearchBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      if (!session) return;
      const h = await adminHealth(session.token);
      setHealth(h);
    } catch (e) {
      setHealth(null);
      setError(e instanceof Error ? e.message : String(e));
    }
    try {
      if (!session) return;
      const d = await adminDocuments(session.token);
      setDocs(Array.isArray(d.documents) ? d.documents : []);
    } catch {
      setDocs([]);
    }
  }

  useEffect(() => {
    setSession(loadAdminSession());
    setReady(true);
  }, []);

  useEffect(() => {
    if (session) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.token]);

  const tools: string[] = health?.tools ?? [];
  const stats = useMemo(
    () => ({
      documents: docs.length,
      chunks: docs.reduce((n, d) => n + (d.chunk_count ?? d.chunks ?? 0), 0),
      tools: tools.length,
    }),
    [docs, tools]
  );

  async function runResearch() {
    if (!question.trim()) return;
    setResearchBusy(true);
    setError("");
    try {
      if (!session) return;
      setResearch(await adminResearch(session.token, question.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResearchBusy(false);
    }
  }

  const navItems = useMemo(() => {
    if (!isOwner(session)) return baseItems;
    return [
      ...baseItems,
      { id: "tabletennis" as View, label: "TableTennisAI", icon: Search },
    ];
  }, [session]);

  async function logout() {
    const token = session?.token;
    clearAdminSession();
    setSession(null);
    setView("overview");
    if (token) {
      try {
        await adminLogout(token);
      } catch {
        /* local session is already cleared */
      }
    }
  }

  if (!ready) {
    return (
      <div className="shell admin-lock">
        <div className="flag-bg" aria-hidden="true" />
        <header className="topbar"><Brand /></header>
        <div className="admin-lock-card"><p className="muted">Checking access…</p></div>
      </div>
    );
  }

  if (!session) return <AdminLogin onSuccess={setSession} />;

  return (
    <div className="admin-shell">
      <div className="admin-flag-bg" aria-hidden="true" />
      <header className="admin-topbar">
        <Brand />
        <div className="admin-title">
          <span>ADMIN WORKSTATION</span>
          <small>Authenticated operations surface</small>
        </div>
        <div className="admin-status">
          <i />
          {health?.ok ? "System operational" : error ? "API issue" : "Checking…"}
        </div>
      </header>

      <div className="admin-layout">
        <aside
          className="admin-nav admin-nav--responsive"
          aria-label="Admin navigation"
        >
          <div className="admin-nav-title">Workstation</div>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                className={view === item.id ? "active" : ""}
                onClick={() => setView(item.id)}
              >
                <Icon size={16} />
                {item.label}
              </button>
            );
          })}
          <div className="admin-nav-foot">
            <div>{session.username} · {session.role}</div>
            <button type="button" className="ghost-btn" onClick={logout} style={{ marginTop: 8 }}>
              Log out
            </button>
          </div>
        </aside>

        <main className={view === "users" ? "admin-main admin-main--identity" : "admin-main"}>
          {error && <div className="admin-banner-err">{error}</div>}

          {view === "overview" && (
            <>
              <div className="page-heading">
                <span className="eyebrow">Command</span>
                <h1>Overview</h1>
                <p>Live model, tools, and knowledge posture for DEFEND AI.</p>
              </div>
              <div className="stat-grid">
                <div className="admin-card stat">
                  <span className="eyebrow">Model</span>
                  <strong>{health?.model ?? "—"}</strong>
                </div>
                <div className="admin-card stat">
                  <span className="eyebrow">Tools</span>
                  <strong>{stats.tools}</strong>
                </div>
                <div className="admin-card stat">
                  <span className="eyebrow">Documents</span>
                  <strong>{stats.documents}</strong>
                </div>
                <div className="admin-card stat">
                  <span className="eyebrow">API</span>
                  <strong>{health?.ok ? "OK" : "DOWN"}</strong>
                </div>
              </div>
              <div className="admin-card">
                <div className="card-title">Registered tools</div>
                <div className="tool-chips">
                  {tools.length ? (
                    tools.map((t) => (
                      <span key={t} className="tool-chip">
                        {t}
                      </span>
                    ))
                  ) : (
                    <p className="muted">No tool list yet — check API health.</p>
                  )}
                </div>
                <button type="button" className="ghost-btn" onClick={refresh} style={{ marginTop: 12 }}>
                  Refresh status
                </button>
              </div>
            </>
          )}

          {view === "knowledge" && (
            <KnowledgeRagPanel
              token={session.token}
              documents={docs}
              onDocumentsChanged={refresh}
            />
          )}

          {view === "background" && <BackgroundCheckPanel />}

          {view === "documents" && <DocumentsPanel docs={docs} />}

          {view === "research" && (
            <ResearchLab
              question={question}
              setQuestion={setQuestion}
              runResearch={runResearch}
              busy={researchBusy}
              result={research}
            />
          )}

          {view === "tabletennis" && isOwner(session) && (
            <TableTennisPanel session={session} />
          )}

          {view === "models" && (
            <>
              <div className="page-heading">
                <span className="eyebrow">Inference</span>
                <h1>Models</h1>
              </div>
              <div className="admin-card">
                <p>
                  Active: <strong>{health?.model ?? "unknown"}</strong>
                </p>
                <p className="muted" style={{ marginTop: 8 }}>
                  Swap with DEFEND_MODEL env + Ollama. Restart api_server after change.
                </p>
              </div>
            </>
          )}

          {view === "tools" && (
            <>
              <div className="page-heading">
                <span className="eyebrow">Capability</span>
                <h1>Tools</h1>
              </div>
              <div className="admin-card">
                <div className="tool-chips">
                  {tools.map((t) => (
                    <span key={t} className="tool-chip">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </>
          )}

          {view === "policy" && (
            <Placeholder
              title="Policy"
              body="ProductionPolicy is loaded by the API. Web read is allowed; destructive tools stay gated. Editable policy surface comes next."
            />
          )}
          {view === "users" && (
            <UsersRolesPanel session={session} />
          )}
          {view === "audit" && (
            <Placeholder
              title="Audit / Traces"
              body="Trace IDs already return on research runs. Persistent audit log storage is next."
            />
          )}
          {view === "settings" && (
            <>
              <div className="page-heading">
                <span className="eyebrow">Config</span>
                <h1>Settings</h1>
              </div>
              <div className="admin-card">
                <p className="muted">
                  Admin credentials are validated server-side from DEFEND_ADMIN_* / DEFEND_OWNER_* environment variables.
                  API model: DEFEND_MODEL. Search: TAVILY_API_KEY.
                </p>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function DocumentsPanel({ docs }: { docs: any[] }) {
  return (
    <>
      <div className="page-heading">
        <span className="eyebrow">Library</span>
        <h1>Documents</h1>
        <p>Stored documents and index state.</p>
      </div>
      <div className="admin-card">
        {docs.length ? (
          docs.map((d, i) => (
            <div className="doc-row" key={d.document_id ?? i}>
              <FileText size={18} />
              <div>
                <strong>{d.title ?? d.name ?? "Untitled"}</strong>
                <span>{d.document_id}</span>
              </div>
            </div>
          ))
        ) : (
          <p className="muted">No documents listed by the API yet.</p>
        )}
      </div>
    </>
  );
}

function ResearchLab({
  question,
  setQuestion,
  runResearch,
  busy,
  result,
}: any) {
  return (
    <>
      <div className="page-heading">
        <span className="eyebrow">Research engine</span>
        <h1>Research Lab</h1>
        <p>Run Research V2 and inspect status, evidence, and sources.</p>
      </div>
      <div className="admin-card research-box">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. BJS adult imprisonment rates by race — cite primary tables"
        />
        <button type="button" onClick={runResearch} disabled={busy}>
          {busy ? "Running…" : "Run research"}
        </button>
      </div>
      {result && (
        <div className="research-result-grid">
          <div className="admin-card">
            <div className="card-title">
              <SlidersHorizontal size={17} /> Run summary
            </div>
            <pre>
              {JSON.stringify(
                {
                  research_status: result.research_status,
                  execution_status: result.execution_status,
                  search_rounds: result.search_rounds,
                  evidence_count: result.evidence_count,
                  trace_id: result.trace_id,
                },
                null,
                2
              )}
            </pre>
          </div>
          <div className="admin-card">
            <div className="card-title">
              <FileSearch size={17} /> Final answer
            </div>
            <p className="result-copy">{result.content ?? result.answer ?? "No answer returned."}</p>
          </div>
        </div>
      )}
    </>
  );
}

function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <>
      <div className="page-heading">
        <span className="eyebrow">Administration</span>
        <h1>{title}</h1>
      </div>
      <div className="admin-card">
        <p className="muted">{body}</p>
      </div>
    </>
  );
}
