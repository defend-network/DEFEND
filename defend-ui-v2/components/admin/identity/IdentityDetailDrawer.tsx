"use client";

import { useEffect, useRef, useState } from "react";

import type { AdminSession } from "@/lib/adminAuth";
import {
  anonymizeAccount,
  deleteAccount,
  getAccount,
  getVisitor,
  getVisitorConversation,
  updateAccount,
  type AccountDetail,
  type AccountDetailQuery,
  type AccountRecord,
  type ConversationSummary,
  type VisitorConversation,
  type VisitorDetail,
} from "@/lib/identityApi";
import { useDialogFocus } from "./useDialogFocus";

type IdentityDetailDrawerProps = {
  session: AdminSession;
  accountId?: string;
  visitorId?: string;
  onClose: () => void;
  onChanged?: () => void;
};

type Confirmation =
  | "disable"
  | "reactivate"
  | "promote"
  | "demote"
  | "anonymize"
  | "delete"
  | null;

const HISTORY_LIMIT = 50;
const MESSAGE_PAGE_SIZE = 50;

function displayDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to load identity details";
}

function bounded<T>(items: T[]): T[] {
  return items.slice(0, HISTORY_LIMIT);
}

function clientLabel(client: Record<string, unknown>): string {
  return [client.browser, client.platform, client.device]
    .filter((value): value is string => typeof value === "string" && value.length > 0)
    .join(" / ") || "—";
}

function safeMetadataEntries(metadata: Record<string, unknown>): string[] {
  return Object.entries(metadata)
    .filter(([key, value]) => {
      if (/(auth|cookie|credential|password|secret|token)/i.test(key)) return false;
      return value === null || ["string", "number", "boolean"].includes(typeof value);
    })
    .slice(0, 10)
    .map(([key, value]) => `${key}: ${String(value).slice(0, 160)}`);
}

export function IdentityDetailDrawer({
  session,
  accountId,
  visitorId,
  onClose,
  onChanged,
}: IdentityDetailDrawerProps) {
  const [accountDetail, setAccountDetail] = useState<AccountDetail | null>(null);
  const [visitorDetail, setVisitorDetail] = useState<VisitorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [linkedVisitorLoading, setLinkedVisitorLoading] = useState(false);
  const [conversation, setConversation] = useState<VisitorConversation | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [conversationTarget, setConversationTarget] = useState<string | null>(null);
  const [conversationMessageOffset, setConversationMessageOffset] = useState(0);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const confirmationRef = useRef<HTMLElement>(null);
  const confirmationInputRef = useRef<HTMLInputElement>(null);
  const conversationRef = useRef<HTMLElement>(null);
  const conversationCloseRef = useRef<HTMLButtonElement>(null);
  const conversationOpenerRef = useRef<HTMLElement | null>(null);
  const selectionGeneration = useRef(0);
  const detailRequestGeneration = useRef(0);
  const conversationGeneration = useRef(0);

  useDialogFocus({
    containerRef: drawerRef,
    initialFocusRef: drawerCloseRef,
    onClose,
  });
  useDialogFocus({
    active: confirmation !== null,
    containerRef: confirmationRef,
    initialFocusRef: confirmationInputRef,
    onClose: closeConfirmation,
  });
  useDialogFocus({
    active: conversationTarget !== null,
    containerRef: conversationRef,
    initialFocusRef: conversationCloseRef,
    onClose: closeConversation,
    returnFocusRef: conversationOpenerRef,
  });

  useEffect(() => {
    const selection = ++selectionGeneration.current;
    const requestGeneration = ++detailRequestGeneration.current;
    let current = true;
    setLoading(true);
    setError(null);
    setAccountDetail(null);
    setVisitorDetail(null);
    conversationGeneration.current += 1;
    setConversationTarget(null);
    setConversationLoading(false);
    setConversation(null);
    setConversationError(null);
    setConversationMessageOffset(0);
    setConfirmation(null);
    setConfirmationText("");
    setFeedback(null);
    setActionPending(false);
    setLinkedVisitorLoading(false);
    const request = accountId
      ? getAccount(session.token, accountId)
      : visitorId
        ? getVisitor(session.token, visitorId)
        : Promise.reject(new Error("No identity record was selected"));
    void request.then(
      (detail) => {
        if (
          !current ||
          selection !== selectionGeneration.current ||
          requestGeneration !== detailRequestGeneration.current
        ) return;
        if (accountId) {
          const accountResult = detail as AccountDetail;
          setAccountDetail(accountResult);
          setDisplayName(accountResult.account.display_name);
        } else {
          setVisitorDetail(detail as VisitorDetail);
        }
        setLoading(false);
      },
      (caught: unknown) => {
        if (
          !current ||
          selection !== selectionGeneration.current ||
          requestGeneration !== detailRequestGeneration.current
        ) return;
        setError(messageFrom(caught));
        setLoading(false);
      },
    );
    return () => {
      current = false;
      selectionGeneration.current += 1;
      detailRequestGeneration.current += 1;
      conversationGeneration.current += 1;
    };
  }, [accountId, session.token, visitorId]);

  async function openConversation(
    targetVisitorId: string,
    summary: ConversationSummary,
  ) {
    const generation = ++conversationGeneration.current;
    conversationOpenerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConversationTarget(summary.conversation_id);
    setConversationLoading(true);
    setConversationError(null);
    setConversation(null);
    setConversationMessageOffset(0);
    try {
      const result = await getVisitorConversation(
        session.token,
        targetVisitorId,
        summary.conversation_id,
      );
      if (generation !== conversationGeneration.current) return;
      setConversation(result);
    } catch (caught) {
      if (generation !== conversationGeneration.current) return;
      setConversationError(messageFrom(caught));
    } finally {
      if (generation === conversationGeneration.current) {
        setConversationLoading(false);
      }
    }
  }

  function closeConversation() {
    conversationGeneration.current += 1;
    setConversationTarget(null);
    setConversationLoading(false);
    setConversation(null);
    setConversationError(null);
    setConversationMessageOffset(0);
  }

  function closeConfirmation() {
    setConfirmation(null);
    setConfirmationText("");
  }

  function beginConfirmation(value: Exclude<Confirmation, null>) {
    setConfirmation(value);
    setConfirmationText("");
    setError(null);
    setFeedback(null);
  }

  async function confirmAccountAction() {
    if (!accountId || !confirmation) return;
    const targetId = accountId;
    const selection = selectionGeneration.current;
    const action = confirmation;
    const detailQuery = linkedVisitorQuery(accountDetail);
    setActionPending(true);
    setError(null);
    try {
      let changedAccount: AccountRecord;
      let successFeedback: string;
      if (action === "disable") {
        const result = await updateAccount(session.token, targetId, {
          status: "disabled",
        });
        changedAccount = result.account;
        successFeedback = "Account disabled";
      } else if (action === "reactivate") {
        const result = await updateAccount(session.token, targetId, {
          status: "active",
        });
        changedAccount = result.account;
        successFeedback = "Account reactivated";
      } else if (action === "promote") {
        const result = await updateAccount(session.token, targetId, {
          role: "admin",
        });
        changedAccount = result.account;
        successFeedback = "Account promoted to administrator";
      } else if (action === "demote") {
        const result = await updateAccount(session.token, targetId, {
          role: "user",
        });
        changedAccount = result.account;
        successFeedback = "Administrator demoted to user";
      } else if (action === "anonymize") {
        const result = await anonymizeAccount(session.token, targetId);
        changedAccount = result.account;
        successFeedback = "Account anonymized";
      } else {
        await deleteAccount(session.token, targetId);
        if (selection !== selectionGeneration.current) return;
        onChanged?.();
        onClose();
        return;
      }
      if (selection !== selectionGeneration.current) return;
      const refreshed = await refreshLoadedAccount(
        changedAccount,
        targetId,
        selection,
        detailQuery,
      );
      if (!refreshed) return;
      setFeedback(successFeedback);
      setConfirmation(null);
      setConfirmationText("");
      onChanged?.();
    } catch (caught) {
      if (selection === selectionGeneration.current) setError(messageFrom(caught));
    } finally {
      if (selection === selectionGeneration.current) setActionPending(false);
    }
  }

  function updateLoadedAccount(account: AccountRecord) {
    setAccountDetail((current) => (current ? { ...current, account } : current));
    setDisplayName(account.display_name);
  }

  async function refreshLoadedAccount(
    account: AccountRecord,
    targetId: string,
    selection: number,
    query?: AccountDetailQuery,
  ): Promise<boolean> {
    if (selection !== selectionGeneration.current) return false;
    updateLoadedAccount(account);
    const requestGeneration = ++detailRequestGeneration.current;
    try {
      const detail = await getAccount(session.token, targetId, query);
      if (
        selection !== selectionGeneration.current ||
        requestGeneration !== detailRequestGeneration.current
      ) return false;
      setAccountDetail(detail);
      setDisplayName(detail.account.display_name);
    } catch (caught) {
      if (
        selection !== selectionGeneration.current ||
        requestGeneration !== detailRequestGeneration.current
      ) return false;
      setError(`Account changed, but details could not be refreshed: ${messageFrom(caught)}`);
    }
    return true;
  }

  async function saveDisplayName(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accountId || !account) return;
    const targetId = accountId;
    const selection = selectionGeneration.current;
    const detailQuery = linkedVisitorQuery(accountDetail);
    const nextName = displayName.trim();
    if (!nextName || nextName === account.display_name) return;
    setActionPending(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await updateAccount(session.token, targetId, {
        display_name: nextName,
      });
      if (selection !== selectionGeneration.current) return;
      const refreshed = await refreshLoadedAccount(
        result.account,
        targetId,
        selection,
        detailQuery,
      );
      if (!refreshed) return;
      setFeedback("Display name updated");
      onChanged?.();
    } catch (caught) {
      if (selection === selectionGeneration.current) setError(messageFrom(caught));
    } finally {
      if (selection === selectionGeneration.current) setActionPending(false);
    }
  }

  function linkedVisitorQuery(
    detail: AccountDetail | null,
  ): AccountDetailQuery | undefined {
    if (!detail) return undefined;
    return {
      linkedVisitorLimit: detail.linked_visitors_page.limit,
      linkedVisitorOffset: detail.linked_visitors_page.offset,
    };
  }

  async function loadLinkedVisitorPage(offset: number) {
    if (!accountId || !accountDetail || linkedVisitorLoading || actionPending) return;
    const targetId = accountId;
    const selection = selectionGeneration.current;
    const requestGeneration = ++detailRequestGeneration.current;
    const loadedDisplayName = accountDetail.account.display_name;
    const query: AccountDetailQuery = {
      linkedVisitorLimit: accountDetail.linked_visitors_page.limit,
      linkedVisitorOffset: offset,
    };
    setLinkedVisitorLoading(true);
    setError(null);
    try {
      const detail = await getAccount(session.token, targetId, query);
      if (
        selection !== selectionGeneration.current ||
        requestGeneration !== detailRequestGeneration.current
      ) return;
      setAccountDetail(detail);
      setDisplayName((current) =>
        current === loadedDisplayName ? detail.account.display_name : current,
      );
    } catch (caught) {
      if (
        selection !== selectionGeneration.current ||
        requestGeneration !== detailRequestGeneration.current
      ) return;
      setError(`Unable to load linked visitors: ${messageFrom(caught)}`);
    } finally {
      if (
        selection === selectionGeneration.current &&
        requestGeneration === detailRequestGeneration.current
      ) {
        setLinkedVisitorLoading(false);
      }
    }
  }

  const account = accountDetail?.account;
  const isSelf = Boolean(
    account && account.email.trim().toLowerCase() === session.username.trim().toLowerCase(),
  );
  const canManageAccount = Boolean(
    account &&
      account.role !== "owner" &&
      (account.role === "user" || session.role === "owner"),
  );
  const canEditName = canManageAccount;
  const canDisable = Boolean(
    canManageAccount &&
      !isSelf &&
      account &&
      account.status !== "disabled" &&
      account.status !== "anonymized",
  );
  const canReactivate = Boolean(
    canManageAccount && !isSelf && account?.status === "disabled",
  );
  const canChangeRole = Boolean(
    canManageAccount && !isSelf && account && session.role === "owner",
  );
  const canDestroy = Boolean(
    account && session.role === "owner" && account.role !== "owner" && !isSelf,
  );
  const requiredConfirmation = confirmation?.toUpperCase() ?? "";
  const linkedVisitorsPage = accountDetail?.linked_visitors_page;
  const linkedVisitorPageStart = linkedVisitorsPage
    ? linkedVisitorsPage.total === 0
      ? 0
      : Math.min(linkedVisitorsPage.offset + 1, linkedVisitorsPage.total)
    : 0;
  const linkedVisitorPageEnd = linkedVisitorsPage
    ? Math.min(
        linkedVisitorsPage.offset + (accountDetail?.linked_visitors.length ?? 0),
        linkedVisitorsPage.total,
      )
    : 0;
  const canLoadPreviousLinkedVisitors = Boolean(
    linkedVisitorsPage && linkedVisitorsPage.offset > 0,
  );
  const canLoadNextLinkedVisitors = Boolean(
    linkedVisitorsPage && linkedVisitorPageEnd < linkedVisitorsPage.total,
  );
  const conversationMessages = conversation?.messages ?? [];
  const messagePageStart = Math.min(
    conversationMessageOffset,
    Math.max(0, conversationMessages.length - 1),
  );
  const messagePageEnd = Math.min(
    messagePageStart + MESSAGE_PAGE_SIZE,
    conversationMessages.length,
  );
  const visibleConversationMessages = conversationMessages.slice(
    messagePageStart,
    messagePageEnd,
  );

  function conversationButtons(
    targetVisitorId: string,
    conversations: ConversationSummary[],
  ) {
    if (conversations.length === 0) return <p>No conversations recorded.</p>;
    return (
      <ul className="identity-history-list">
        {bounded(conversations).map((item) => {
          const label = item.title || item.conversation_id;
          return (
            <li key={item.conversation_id}>
              <span>{label}</span>
              <span>{item.message_count ?? 0} messages</span>
              <button
                type="button"
                className="ghost-btn"
                aria-label={`Open conversation ${label}`}
                onClick={() => openConversation(targetVisitorId, item)}
              >
                Open conversation
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className="identity-drawer-backdrop">
      <aside
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="identity-detail-title"
        className="admin-card identity-detail-drawer"
      >
        <header className="identity-detail-header">
          <div>
            <span className="eyebrow">Audited identity detail</span>
            <h2 id="identity-detail-title">
              {accountId ? "Account detail" : "Visitor detail"}
            </h2>
          </div>
          <button ref={drawerCloseRef} type="button" className="ghost-btn" onClick={onClose}>
            Close details
          </button>
        </header>

        {loading && <p role="status">Loading identity details...</p>}
        {!loading && error && !accountDetail && !visitorDetail && (
          <p role="alert">{error}</p>
        )}

        {accountDetail && account && (
          <div className="identity-detail-content">
            <section>
              <h3>{account.display_name}</h3>
              <dl>
                <dt>Email</dt><dd>{account.email}</dd>
                <dt>Role</dt><dd>{account.role}</dd>
                <dt>Status</dt><dd>{account.status}</dd>
                <dt>Created</dt><dd>{displayDate(account.created_at)}</dd>
                <dt>Last access</dt><dd>{displayDate(account.last_access_at)}</dd>
              </dl>
              {canEditName && (
                <form className="identity-action-form" onSubmit={saveDisplayName}>
                  <label>
                    Display name
                    <input
                      value={displayName}
                      maxLength={160}
                      disabled={linkedVisitorLoading}
                      onChange={(event) => setDisplayName(event.target.value)}
                    />
                  </label>
                  <button
                    type="submit"
                    disabled={
                      actionPending ||
                      linkedVisitorLoading ||
                      displayName.trim().length === 0 ||
                      displayName.trim() === account.display_name
                    }
                  >
                    {actionPending ? "Saving..." : "Save display name"}
                  </button>
                </form>
              )}
            </section>

            <section>
              <h3>Account sessions</h3>
              {accountDetail.sessions.length === 0 ? <p>No sessions recorded.</p> : (
                <ul className="identity-history-list">
                  {bounded(accountDetail.sessions).map((item) => (
                    <li key={item.session_id}>
                      <span>{displayDate(item.created_at)}</span>
                      <span>Last seen {displayDate(item.last_seen_at)}</span>
                      <span>{item.revoked_at ? "Revoked" : "Active or expired"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3>Login and activation history</h3>
              {accountDetail.login_events.length === 0 ? <p>No login events recorded.</p> : (
                <ul className="identity-history-list">
                  {bounded(accountDetail.login_events).map((item) => (
                    <li key={item.event_id}>
                      <span>{item.outcome}</span>
                      <span>{displayDate(item.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3>Invitation history</h3>
              {accountDetail.invitations.length === 0 ? <p>No invitations recorded.</p> : (
                <ul className="identity-history-list">
                  {bounded(accountDetail.invitations).map((item) => (
                    <li key={item.invitation_id}>
                      <span>{item.delivery_status}</span>
                      <span>Created {displayDate(item.created_at)}</span>
                      <span>Expires {displayDate(item.expires_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3>Linked visitors and activity</h3>
              {linkedVisitorsPage && (
                <>
                  <nav
                    className="identity-pagination"
                    aria-label="Linked visitors pagination"
                    aria-busy={linkedVisitorLoading}
                  >
                    <button
                      type="button"
                      className="ghost-btn"
                      aria-disabled={
                        !canLoadPreviousLinkedVisitors ||
                        linkedVisitorLoading ||
                        actionPending
                      }
                      onClick={() => {
                        if (
                          !canLoadPreviousLinkedVisitors ||
                          linkedVisitorLoading ||
                          actionPending
                        ) return;
                        void loadLinkedVisitorPage(
                          Math.max(
                            0,
                            linkedVisitorsPage.offset - linkedVisitorsPage.limit,
                          ),
                        );
                      }}
                    >
                      Previous linked visitors
                    </button>
                    <span aria-live="polite">
                      Showing linked visitors {linkedVisitorPageStart}-
                      {linkedVisitorPageEnd} of {linkedVisitorsPage.total}
                    </span>
                    <button
                      type="button"
                      className="ghost-btn"
                      aria-disabled={
                        !canLoadNextLinkedVisitors ||
                        linkedVisitorLoading ||
                        actionPending
                      }
                      onClick={() => {
                        if (
                          !canLoadNextLinkedVisitors ||
                          linkedVisitorLoading ||
                          actionPending
                        ) return;
                        void loadLinkedVisitorPage(
                          linkedVisitorsPage.offset + linkedVisitorsPage.limit,
                        );
                      }}
                    >
                      Next linked visitors
                    </button>
                  </nav>
                  <p>
                    Activity history for this page is bounded: {" "}
                    {linkedVisitorsPage.history_rows_returned} rows returned with a {" "}
                    {linkedVisitorsPage.history_row_limit}-row limit.
                  </p>
                  {linkedVisitorLoading && (
                    <p role="status">Loading linked visitors...</p>
                  )}
                </>
              )}
              {accountDetail.linked_visitors.length === 0 ? <p>No linked visitors.</p> : (
                bounded(accountDetail.linked_visitors).map((linked) => (
                  <article key={linked.visitor_id}>
                    <h4>{linked.visitor_id}</h4>
                    <p>Recent IP: {linked.telemetry.recent_ip ?? "—"}</p>
                    <p>{linked.sessions.length} sessions / {linked.usage_events.length} usage events</p>
                    {linked.connections.length > 0 && (
                      <>
                        <h5>IP and device history</h5>
                        <ul className="identity-history-list">
                          {bounded(linked.connections).map((item) => (
                            <li key={item.connection_id}>
                              <span>{item.ip_address}</span>
                              <span>{item.browser} / {item.platform} / {item.device}</span>
                              <span>{displayDate(item.observed_at)}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                    {linked.usage_events.length > 0 && (
                      <>
                        <h5>Usage activity</h5>
                        <ul className="identity-history-list">
                          {bounded(linked.usage_events).map((item) => (
                            <li key={item.event_id}>
                              <span>{item.event_type}</span>
                              <span>{item.route ?? "—"}</span>
                              <span>{displayDate(item.created_at)}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                    {conversationButtons(linked.visitor_id, linked.conversations)}
                  </article>
                ))
              )}
            </section>

            {(canDisable || canReactivate || canChangeRole || canDestroy) && (
              <section aria-label="Account actions" className="identity-danger-zone">
                <h3>Account actions</h3>
                {canDisable && (
                  <button
                    type="button"
                    disabled={linkedVisitorLoading}
                    onClick={() => beginConfirmation("disable")}
                  >
                    Disable account
                  </button>
                )}
                {canReactivate && (
                  <button
                    type="button"
                    disabled={linkedVisitorLoading}
                    onClick={() => beginConfirmation("reactivate")}
                  >
                    Reactivate account
                  </button>
                )}
                {canChangeRole && account.role === "user" && (
                  <button
                    type="button"
                    disabled={linkedVisitorLoading}
                    onClick={() => beginConfirmation("promote")}
                  >
                    Promote to administrator
                  </button>
                )}
                {canChangeRole && account.role === "admin" && (
                  <button
                    type="button"
                    disabled={linkedVisitorLoading}
                    onClick={() => beginConfirmation("demote")}
                  >
                    Demote to user
                  </button>
                )}
                {canDestroy && (
                  <>
                    <button
                      type="button"
                      disabled={linkedVisitorLoading}
                      onClick={() => beginConfirmation("anonymize")}
                    >
                      Anonymize account
                    </button>
                    <button
                      type="button"
                      disabled={linkedVisitorLoading}
                      onClick={() => beginConfirmation("delete")}
                    >
                      Delete account
                    </button>
                  </>
                )}
              </section>
            )}
          </div>
        )}

        {visitorDetail && (
          <div className="identity-detail-content">
            <section>
              <h3>{visitorDetail.visitor.visitor_id}</h3>
              <dl>
                <dt>Linked account</dt>
                <dd>{visitorDetail.linked_account?.email ?? "Anonymous"}</dd>
                <dt>Client</dt>
                <dd>{clientLabel(visitorDetail.visitor.client_meta)}</dd>
                <dt>Language</dt>
                <dd>{String(visitorDetail.visitor.client_meta.language ?? "—")}</dd>
                <dt>Fingerprint hash</dt>
                <dd>{visitorDetail.visitor.fingerprint_hmac}</dd>
                <dt>First seen</dt><dd>{displayDate(visitorDetail.visitor.first_seen)}</dd>
                <dt>Last seen</dt><dd>{displayDate(visitorDetail.visitor.last_seen)}</dd>
                <dt>Seen count</dt><dd>{visitorDetail.visitor.seen_count}</dd>
              </dl>
            </section>
            <section>
              <h3>Connection history</h3>
              {visitorDetail.connections.length === 0 ? <p>No connection history recorded.</p> : (
                <ul className="identity-history-list">
                  {bounded(visitorDetail.connections).map((item) => (
                    <li key={item.connection_id}>
                      <span>{item.ip_address}</span>
                      <span>{item.browser} / {item.platform} / {item.device}</span>
                      <span>{displayDate(item.observed_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3>Sessions and usage</h3>
              {visitorDetail.sessions.length === 0 ? (
                <p>No visitor sessions recorded.</p>
              ) : (
                <ul className="identity-history-list">
                  {bounded(visitorDetail.sessions).map((item) => (
                    <li key={item.session_id}>
                      <span>{item.session_id}</span>
                      <span>{clientLabel(item.client_meta)}</span>
                      <span>Created {displayDate(item.created_at)}</span>
                      <span>Last seen {displayDate(item.last_seen)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {visitorDetail.usage_events.length === 0 ? (
                <p>No usage events recorded.</p>
              ) : (
                <ul className="identity-history-list">
                  {bounded(visitorDetail.usage_events).map((item) => {
                    const metadata = safeMetadataEntries(item.metadata);
                    return (
                      <li key={item.event_id}>
                        <span>{item.event_type}</span>
                        <span>{item.route ?? "—"}</span>
                        <span>{item.model ?? "—"}</span>
                        <span>{item.status ?? item.research_status ?? "—"}</span>
                        <span>{displayDate(item.created_at)}</span>
                        {metadata.map((entry) => <span key={entry}>{entry}</span>)}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            <section>
              <h3>Conversations</h3>
              {conversationButtons(
                visitorDetail.visitor.visitor_id,
                visitorDetail.conversations,
              )}
            </section>
          </div>
        )}

        {confirmation && (
          <section
            ref={confirmationRef}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="identity-confirm-title"
          >
            <h3 id="identity-confirm-title">Confirm {confirmation}</h3>
            <p>This administrative action is audited.</p>
            <label>
              Type {requiredConfirmation} to confirm
              <input
                ref={confirmationInputRef}
                aria-label={`Type ${requiredConfirmation} to confirm`}
                value={confirmationText}
                autoComplete="off"
                onChange={(event) => setConfirmationText(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={confirmationText !== requiredConfirmation || actionPending}
              onClick={confirmAccountAction}
            >
              {actionPending ? "Working..." : `Confirm ${confirmation}`}
            </button>
            <button type="button" className="ghost-btn" onClick={closeConfirmation}>
              Cancel
            </button>
          </section>
        )}

        {feedback && <p role="status">{feedback}</p>}
        {!loading && error && accountDetail && <p role="alert">{error}</p>}

        {conversationTarget && (
          <section
            ref={conversationRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="conversation-content-title"
            className="identity-conversation-view"
          >
            <header>
              <h3 id="conversation-content-title">Audited conversation content</h3>
              <button
                ref={conversationCloseRef}
                type="button"
                className="ghost-btn"
                onClick={closeConversation}
              >
                Close conversation
              </button>
            </header>
            {conversationLoading && <p role="status">Loading conversation...</p>}
            {conversationError && <p role="alert">{conversationError}</p>}
            {conversation && (
              <>
                {conversationMessages.length > 0 && (
                  <nav
                    className="identity-pagination"
                    aria-label="Conversation message pagination"
                  >
                    {messagePageStart > 0 && (
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() =>
                          setConversationMessageOffset((offset) =>
                            Math.max(0, offset - MESSAGE_PAGE_SIZE),
                          )
                        }
                      >
                        Show previous messages
                      </button>
                    )}
                    <span aria-live="polite">
                      Showing messages {messagePageStart + 1}-{messagePageEnd} of{" "}
                      {conversationMessages.length}
                    </span>
                    {messagePageEnd < conversationMessages.length && (
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() =>
                          setConversationMessageOffset((offset) =>
                            offset + MESSAGE_PAGE_SIZE
                          )
                        }
                      >
                        Show next messages
                      </button>
                    )}
                  </nav>
                )}
                <ol className="identity-message-list">
                  {visibleConversationMessages.map((message) => (
                    <li key={message.message_id}>
                      <strong>{message.role}</strong>
                      <p>{message.content}</p>
                      <time>{displayDate(message.created_at)}</time>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </section>
        )}
      </aside>
    </div>
  );
}
