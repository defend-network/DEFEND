"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Diagnostics,
  SetupSummary,
  TestAllResult,
  getSetupDiagnostics,
  getSetupSummary,
  testAllSetupProviders,
} from "@/lib/setupApi";
import { AdminSession } from "@/lib/adminAuth";
import ProviderCard from "./ProviderCard";

const COMPACT_WIDTH = 760;

const BADGE_LABEL: Record<string, string> = {
  NOT_CONFIGURED: "Not configured",
  NOT_TESTED: "Not tested",
  HEALTHY: "Healthy",
  DEGRADED: "Degraded",
  RATE_LIMITED: "Rate limited",
  UNAVAILABLE: "Unavailable",
  AUTH_FAILED: "Auth failed",
};

type Props = {
  session: AdminSession;
};

export default function SetupIntegrationsPanel({ session }: Props) {
  const [summary, setSummary] = useState<SetupSummary | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [activeTab, setActiveTab] = useState<string>("core");
  const [compact, setCompact] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [testingAll, setTestingAll] = useState<TestAllResult | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const shellRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(
    () => setRefreshVersion((version) => version + 1),
    []
  );

  useEffect(() => {
    let cancelled = false;
    getSetupSummary(session.token)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Setup data unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [session.token, refreshVersion]);

  useEffect(() => {
    if (activeTab !== "diagnostics") return;
    let cancelled = false;
    getSetupDiagnostics(session.token)
      .then((data) => {
        if (!cancelled) setDiagnostics(data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Diagnostics unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [session.token, activeTab, refreshVersion]);

  useEffect(() => {
    function measure() {
      const width = shellRef.current?.clientWidth ?? 0;
      setCompact(width > 0 && width < COMPACT_WIDTH);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const categories = summary?.categories ?? [];
  const activeCategory = categories.find((c) => c.category_id === activeTab);

  async function runTestAll() {
    setBusy("test-all");
    setError(null);
    try {
      const result = await testAllSetupProviders(session.token);
      setTestingAll(result);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "TEST ALL failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      ref={shellRef}
      className="setup-shell"
      data-setup-shell
      style={{ overflowY: "hidden" }}
    >
      <header className="setup-topbar">
        <div className="setup-heading">
          <span className="eyebrow">Restricted — admin</span>
          <h1>Setup &amp; Integrations</h1>
        </div>
        <div className="setup-actions">
          <button
            type="button"
            className="ghost-btn"
            disabled={busy !== null}
            onClick={refresh}
          >
            Refresh
          </button>
          <button
            type="button"
            className="setup-test-all"
            disabled={busy !== null}
            onClick={runTestAll}
          >
            {busy === "test-all" ? "Testing all…" : "TEST ALL CONFIGURED"}
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="setup-banner-err">
          {error}
        </p>
      )}

      {testingAll && (
        <div className="setup-test-all-result" role="status">
          Tested {testingAll.tested} provider(s)
          {testingAll.skipped.length > 0 &&
            `; skipped ${testingAll.skipped.length} (${testingAll.skipped
              .slice(0, 3)
              .map((s) => s.reason)
              .join(", ")}${testingAll.skipped.length > 3 ? ", …" : ""})`}
          .
        </div>
      )}

      {!summary ? (
        <p className="setup-loading">Loading provider registry…</p>
      ) : (
        <>
          <nav
            className="setup-tabbar"
            role="tablist"
            aria-label="Provider categories"
            hidden={compact}
          >
            {categories.map((category) => (
              <button
                key={category.category_id}
                type="button"
                role="tab"
                id={`tab-${category.category_id}`}
                aria-selected={activeTab === category.category_id}
                aria-controls={`panel-${category.category_id}`}
                className={
                  activeTab === category.category_id
                    ? "setup-tab setup-tab-active"
                    : "setup-tab"
                }
                onClick={() => setActiveTab(category.category_id)}
              >
                {category.display_name}
              </button>
            ))}
          </nav>
          <div className="setup-tabselect" hidden={!compact}>
            <label htmlFor="setup-category-select">Category</label>
            <select
              id="setup-category-select"
              value={activeTab}
              onChange={(e) => setActiveTab(e.target.value)}
            >
              {categories.map((category) => (
                <option key={category.category_id} value={category.category_id}>
                  {category.display_name}
                </option>
              ))}
            </select>
          </div>

          <main
            id={`panel-${activeTab}`}
            role="tabpanel"
            aria-labelledby={`tab-${activeTab}`}
            className="setup-body"
            style={{ overflowY: "auto" }}
          >
            {activeTab === "diagnostics" ? (
              <DiagnosticsMatrix rows={diagnostics?.rows ?? []} />
            ) : activeCategory ? (
              <div className="setup-grid">
                {activeCategory.providers.map((provider) => (
                  <ProviderCard
                    key={provider.provider_id}
                    provider={provider}
                    token={session.token}
                    onChanged={refresh}
                  />
                ))}
                {activeCategory.providers.length === 0 && (
                  <p className="setup-empty">
                    No providers in this category.
                  </p>
                )}
              </div>
            ) : null}
          </main>
        </>
      )}
    </div>
  );
}

function DiagnosticsMatrix({ rows }: { rows: Diagnostics["rows"] }) {
  return (
    <div className="setup-diagnostics">
      <div className="setup-diagnostics-scroll">
        <table className="setup-matrix">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Category</th>
              <th>Product(s)</th>
              <th>Config</th>
              <th>Auth</th>
              <th>Health</th>
              <th>Quota</th>
              <th>Last success</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.provider_id}>
                <td>
                  <span className="setup-matrix-name">{row.display_name}</span>
                  <span className="setup-matrix-id">{row.provider_id}</span>
                </td>
                <td>{row.category}</td>
                <td>{row.products.join(", ")}</td>
                <td>
                  {row.enabled ? (row.configured ? "configured" : "missing") : "disabled"}
                </td>
                <td>{row.auth_type}</td>
                <td>
                  <span
                    className={`setup-badge setup-badge-${row.health_badge.toLowerCase()}`}
                  >
                    {BADGE_LABEL[row.health_badge] ?? row.health_badge}
                  </span>
                </td>
                <td>
                  {row.remaining_quota != null
                    ? String(row.remaining_quota)
                    : "—"}
                </td>
                <td>{row.last_success_at ?? "—"}</td>
                <td className="setup-matrix-detail">{row.detail ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="setup-empty">No diagnostics yet.</p>}
    </div>
  );
}