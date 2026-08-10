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
type RequestState = { q: string; offset: number };

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
  limit: number;
  offset: number;
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
  const [requests, setRequests] = useState<TabValues<RequestState>>({
    accounts: { q: "", offset: 0 },
    visitors: { q: "", offset: 0 },
    invitations: { q: "", offset: 0 },
  });
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [page, setPage] = useState<PageState>({
    tab: "accounts",
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0,
    loading: true,
    error: null,
  });
  const requestGeneration = useRef(0);

  const query = queries[activeTab];
  const request = requests[activeTab];
  const label = labels[activeTab];

  useEffect(() => {
    const tab = activeTab;
    const value = queries[tab];
    const timer = window.setTimeout(() => {
      setRequests((current) => {
        const committed = current[tab];
        if (committed.q === value) return current;
        return { ...current, [tab]: { q: value, offset: 0 } };
      });
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
      limit: PAGE_SIZE,
      offset: request.offset,
      loading: true,
      error: null,
    }));

    const queryOptions = { q: request.q, limit: PAGE_SIZE, offset: request.offset };
    let pageRequest: Promise<Page<IdentitySummary>>;
    if (activeTab === "accounts") {
      pageRequest = listAccounts(session.token, queryOptions);
    } else if (activeTab === "visitors") {
      pageRequest = listVisitors(session.token, queryOptions);
    } else {
      pageRequest = listInvitations(session.token, queryOptions);
    }

    void pageRequest.then(
      (result) => {
        if (!current || generation !== requestGeneration.current) return;
        const total = Math.max(0, result.total);
        const returnedLimit = result.limit > 0 ? result.limit : PAGE_SIZE;
        const maxOffset =
          total === 0 ? 0 : Math.floor((total - 1) / returnedLimit) * returnedLimit;
        if (result.items.length === 0 && request.offset > maxOffset) {
          setRequests((existing) => ({
            ...existing,
            [activeTab]: { q: request.q, offset: maxOffset },
          }));
          return;
        }
        setPage({
          tab: activeTab,
          items: result.items,
          total,
          limit: returnedLimit,
          offset: Math.max(0, result.offset),
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
          limit: PAGE_SIZE,
          offset: request.offset,
          loading: false,
          error: errorMessage(error),
        });
      },
    );

    return () => {
      current = false;
    };
  }, [activeTab, refreshVersion, request.offset, request.q, session.token]);

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
    document.getElementById(`identity-tab-${nextTab}`)?.focus();
  }

  function handleSearch(value: string) {
    setQueries((current) => ({ ...current, [activeTab]: value }));
  }

  function movePage(delta: number) {
    setRequests((current) => {
      const loadedOffset =
        page.tab === activeTab && !page.loading
          ? page.offset
          : current[activeTab].offset;
      const pageStep =
        page.tab === activeTab && !page.loading ? page.limit : PAGE_SIZE;
      return {
        ...current,
        [activeTab]: {
          ...current[activeTab],
          offset: Math.max(0, loadedOffset + delta * pageStep),
        },
      };
    });
  }

  const isCurrentPage = page.tab === activeTab;
  const loading = !isCurrentPage || page.loading;
  const error = isCurrentPage ? page.error : null;
  const items = isCurrentPage ? page.items : [];
  const total = isCurrentPage ? page.total : 0;
  const pageOffset = isCurrentPage ? page.offset : request.offset;
  const firstResult = items.length === 0 ? 0 : pageOffset + 1;
  const lastResult =
    items.length === 0 ? 0 : Math.min(pageOffset + items.length, total);
  const canGoBack = pageOffset > 0;
  const canGoForward = items.length > 0 && pageOffset + items.length < total;

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

        {TAB_ORDER.map((tab) => (
          <div
            key={tab}
            id={`identity-panel-${tab}`}
            role="tabpanel"
            aria-labelledby={`identity-tab-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
            hidden={activeTab !== tab}
          >
            {activeTab === tab && (
              <>
                {loading && <p role="status">Loading {label.toLowerCase()}...</p>}
                {!loading && error && <p role="alert">{error}</p>}
                {!loading && !error && items.length === 0 && (
                  <p>No {label.toLowerCase()} found.</p>
                )}
                {!loading && !error && items.length > 0 && tab === "accounts" && (
                  <AccountsTab
                    accounts={items as AccountSummary[]}
                    onSelect={onSelectAccount}
                  />
                )}
                {!loading && !error && items.length > 0 && tab === "visitors" && (
                  <VisitorsTab
                    visitors={items as VisitorSummary[]}
                    onSelect={onSelectVisitor}
                  />
                )}
                {!loading && !error && items.length > 0 && tab === "invitations" && (
                  <InvitationsTab
                    invitations={items as InvitationSummary[]}
                    onSelect={onSelectInvitation}
                  />
                )}
              </>
            )}
          </div>
        ))}

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
