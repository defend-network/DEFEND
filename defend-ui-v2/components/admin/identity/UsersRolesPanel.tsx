"use client";

import { useEffect, useRef, useState } from "react";

import type { AdminSession } from "@/lib/adminAuth";
import {
  listAccounts,
  listInvitations,
  listVisitors,
  type AccountSummary,
  type InvitationSummary,
  type Page,
  type VisitorSummary,
} from "@/lib/identityApi";
import { AccountsTab } from "./AccountsTab";
import { InvitationsTab } from "./InvitationsTab";
import { VisitorsTab } from "./VisitorsTab";

const PAGE_SIZE = 50;
const TAB_ORDER = ["accounts", "visitors", "invitations"] as const;

type IdentityTab = (typeof TAB_ORDER)[number];
type IdentitySummary = AccountSummary | VisitorSummary | InvitationSummary;
type TabValues<T> = Record<IdentityTab, T>;

type UsersRolesPanelProps = {
  session: AdminSession;
  onSelectAccount?: (account: AccountSummary) => void;
  onSelectVisitor?: (visitor: VisitorSummary) => void;
  onSelectInvitation?: (invitation: InvitationSummary) => void;
};

type PageState = {
  tab: IdentityTab;
  items: IdentitySummary[];
  total: number;
  loading: boolean;
  error: string | null;
};

const labels: Record<IdentityTab, string> = {
  accounts: "Accounts",
  visitors: "Visitors",
  invitations: "Invitations",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to load identity records";
}

export function UsersRolesPanel({
  session,
  onSelectAccount,
  onSelectVisitor,
  onSelectInvitation,
}: UsersRolesPanelProps) {
  const [activeTab, setActiveTab] = useState<IdentityTab>("accounts");
  const [queries, setQueries] = useState<TabValues<string>>({
    accounts: "",
    visitors: "",
    invitations: "",
  });
  const [debouncedQueries, setDebouncedQueries] = useState<TabValues<string>>({
    accounts: "",
    visitors: "",
    invitations: "",
  });
  const [offsets, setOffsets] = useState<TabValues<number>>({
    accounts: 0,
    visitors: 0,
    invitations: 0,
  });
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [page, setPage] = useState<PageState>({
    tab: "accounts",
    items: [],
    total: 0,
    loading: true,
    error: null,
  });
  const requestGeneration = useRef(0);

  const query = queries[activeTab];
  const debouncedQuery = debouncedQueries[activeTab];
  const offset = offsets[activeTab];
  const label = labels[activeTab];

  useEffect(() => {
    const tab = activeTab;
    const value = queries[tab];
    const timer = window.setTimeout(() => {
      setDebouncedQueries((current) =>
        current[tab] === value ? current : { ...current, [tab]: value },
      );
    }, 300);
    return () => window.clearTimeout(timer);
  }, [activeTab, queries]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    let current = true;
    setPage((existing) => ({
      ...existing,
      tab: activeTab,
      items: [],
      total: 0,
      loading: true,
      error: null,
    }));

    const queryOptions = { q: debouncedQuery, limit: PAGE_SIZE, offset };
    let request: Promise<Page<IdentitySummary>>;
    if (activeTab === "accounts") {
      request = listAccounts(session.token, queryOptions);
    } else if (activeTab === "visitors") {
      request = listVisitors(session.token, queryOptions);
    } else {
      request = listInvitations(session.token, queryOptions);
    }

    void request.then(
      (result) => {
        if (!current || generation !== requestGeneration.current) return;
        setPage({
          tab: activeTab,
          items: result.items,
          total: result.total,
          loading: false,
          error: null,
        });
      },
      (error: unknown) => {
        if (!current || generation !== requestGeneration.current) return;
        setPage({
          tab: activeTab,
          items: [],
          total: 0,
          loading: false,
          error: errorMessage(error),
        });
      },
    );

    return () => {
      current = false;
    };
  }, [activeTab, debouncedQuery, offset, refreshVersion, session.token]);

  function selectTab(tab: IdentityTab) {
    setActiveTab(tab);
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    const currentIndex = TAB_ORDER.indexOf(activeTab);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % TAB_ORDER.length;
    if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + TAB_ORDER.length) % TAB_ORDER.length;
    }
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = TAB_ORDER.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = TAB_ORDER[nextIndex];
    selectTab(nextTab);
    window.requestAnimationFrame(() => {
      document.getElementById(`identity-tab-${nextTab}`)?.focus();
    });
  }

  function handleSearch(value: string) {
    setQueries((current) => ({ ...current, [activeTab]: value }));
    setOffsets((current) => ({ ...current, [activeTab]: 0 }));
  }

  function movePage(delta: number) {
    setOffsets((current) => ({
      ...current,
      [activeTab]: Math.max(0, current[activeTab] + delta * PAGE_SIZE),
    }));
  }

  const isCurrentPage = page.tab === activeTab;
  const loading = !isCurrentPage || page.loading;
  const error = isCurrentPage ? page.error : null;
  const items = isCurrentPage ? page.items : [];
  const total = isCurrentPage ? page.total : 0;
  const firstResult = total === 0 ? 0 : offset + 1;
  const lastResult = Math.min(offset + PAGE_SIZE, total);
  const canGoBack = offset > 0;
  const canGoForward = offset + PAGE_SIZE < total;

  return (
    <section className="identity-workspace" aria-labelledby="identity-heading">
      <div className="page-heading">
        <span className="eyebrow">Identity administration</span>
        <h1 id="identity-heading">Users &amp; Roles</h1>
        <p>Search and inspect registered accounts, visitors, and invitations.</p>
      </div>

      <div className="admin-card identity-card">
        <div role="tablist" aria-label="Identity record type" className="identity-tabs">
          {TAB_ORDER.map((tab) => (
            <button
              key={tab}
              id={`identity-tab-${tab}`}
              type="button"
              role="tab"
              aria-controls={`identity-panel-${tab}`}
              aria-selected={activeTab === tab}
              tabIndex={activeTab === tab ? 0 : -1}
              onClick={() => selectTab(tab)}
              onKeyDown={handleTabKeyDown}
            >
              {labels[tab]}
            </button>
          ))}
        </div>

        <div className="identity-toolbar">
          <label>
            <span className="sr-only">Search {label.toLowerCase()}</span>
            <input
              type="search"
              aria-label={`Search ${label.toLowerCase()}`}
              value={query}
              onChange={(event) => handleSearch(event.target.value)}
              placeholder={`Search ${label.toLowerCase()}`}
            />
          </label>
          <button
            type="button"
            className="ghost-btn"
            aria-label={`Refresh ${label.toLowerCase()}`}
            onClick={() => setRefreshVersion((value) => value + 1)}
          >
            Refresh
          </button>
        </div>

        <div
          id={`identity-panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`identity-tab-${activeTab}`}
          tabIndex={0}
        >
          {loading && <p role="status">Loading {label.toLowerCase()}...</p>}
          {!loading && error && <p role="alert">{error}</p>}
          {!loading && !error && items.length === 0 && (
            <p>No {label.toLowerCase()} found.</p>
          )}
          {!loading && !error && items.length > 0 && activeTab === "accounts" && (
            <AccountsTab
              accounts={items as AccountSummary[]}
              onSelect={onSelectAccount}
            />
          )}
          {!loading && !error && items.length > 0 && activeTab === "visitors" && (
            <VisitorsTab
              visitors={items as VisitorSummary[]}
              onSelect={onSelectVisitor}
            />
          )}
          {!loading && !error && items.length > 0 && activeTab === "invitations" && (
            <InvitationsTab
              invitations={items as InvitationSummary[]}
              onSelect={onSelectInvitation}
            />
          )}
        </div>

        {!loading && !error && (
          <nav className="identity-pagination" aria-label={`${label} pagination`}>
            <button
              type="button"
              className="ghost-btn"
              aria-label="Previous page"
              disabled={!canGoBack}
              onClick={() => movePage(-1)}
            >
              Previous
            </button>
            <span aria-live="polite">
              {firstResult}-{lastResult} of {total}
            </span>
            <button
              type="button"
              className="ghost-btn"
              aria-label="Next page"
              disabled={!canGoForward}
              onClick={() => movePage(1)}
            >
              Next
            </button>
          </nav>
        )}
      </div>
    </section>
  );
}
