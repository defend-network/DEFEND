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

type Confirmation = "disable" | "anonymize" | "delete" | null;

const HISTORY_LIMIT = 50;

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
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [conversation, setConversation] = useState<VisitorConversation | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [conversationTarget, setConversationTarget] = useState<string | null>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const confirmationRef = useRef<HTMLElement>(null);
  const confirmationInputRef = useRef<HTMLInputElement>(null);
  const conversationRef = useRef<HTMLElement>(null);
  const conversationCloseRef = useRef<HTMLButtonElement>(null);
  const conversationOpenerRef = useRef<HTMLElement | null>(null);
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
    const request = accountId
      ? getAccount(session.token, accountId)
      : visitorId
        ? getVisitor(session.token, visitorId)
        : Promise.reject(new Error("No identity record was selected"));
    void request.then(
      (detail) => {
        if (!current) return;
        if (accountId) setAccountDetail(detail as AccountDetail);
        else setVisitorDetail(detail as VisitorDetail);
        setLoading(false);
      },
      (caught: unknown) => {
        if (!current) return;
        setError(messageFrom(caught));
        setLoading(false);
      },
    );
    return () => {
      current = false;
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
    setActionPending(true);
    setError(null);
    try {
      if (confirmation === "disable") {
        const result = await updateAccount(session.token, accountId, {
          status: "disabled",
        });
        updateLoadedAccount(result.account);
        setFeedback("Account disabled");
      } else if (confirmation === "anonymize") {
        const result = await anonymizeAccount(session.token, accountId);
        updateLoadedAccount(result.account);
        setFeedback("Account anonymized");
      } else {
        await deleteAccount(session.token, accountId);
        onChanged?.();
        onClose();
        return;
      }
      setConfirmation(null);
      setConfirmationText("");
      onChanged?.();
    } catch (caught) {
      setError(messageFrom(caught));
    } finally {
      setActionPending(false);
    }
  }

  function updateLoadedAccount(account: AccountRecord) {
    setAccountDetail((current) => (current ? { ...current, account } : current));
  }

  const account = accountDetail?.account;
  const canDisable = Boolean(
    account &&
      account.role !== "owner" &&
      account.status !== "disabled" &&
      account.status !== "anonymized" &&
      (account.role === "user" || session.role === "owner"),
  );
  const canDestroy = Boolean(
    account && session.role === "owner" && account.role !== "owner",
  );
  const requiredConfirmation = confirmation?.toUpperCase() ?? "";

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

            {(canDisable || canDestroy) && (
              <section aria-label="Account actions" className="identity-danger-zone">
                <h3>Account actions</h3>
                {canDisable && (
                  <button type="button" onClick={() => beginConfirmation("disable")}>
                    Disable account
                  </button>
                )}
                {canDestroy && (
                  <>
                    <button type="button" onClick={() => beginConfirmation("anonymize")}>
                      Anonymize account
                    </button>
                    <button type="button" onClick={() => beginConfirmation("delete")}>
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
              <ol className="identity-message-list">
                {bounded(conversation.messages).map((message) => (
                  <li key={message.message_id}>
                    <strong>{message.role}</strong>
                    <p>{message.content}</p>
                    <time>{displayDate(message.created_at)}</time>
                  </li>
                ))}
              </ol>
            )}
          </section>
        )}
      </aside>
    </div>
  );
}
