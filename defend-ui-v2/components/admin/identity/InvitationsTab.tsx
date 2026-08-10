"use client";

import { useRef, useState } from "react";

import type { AdminSession } from "@/lib/adminAuth";
import {
  regenerateInvitation,
  resendInvitation,
  revokeInvitation,
  type InvitationSummary,
} from "@/lib/identityApi";
import { useDialogFocus } from "./useDialogFocus";

type InvitationsTabProps = {
  invitations: InvitationSummary[];
  session: AdminSession;
  onSelect?: (invitation: InvitationSummary) => void;
  onChanged?: () => void;
};

function displayDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function InvitationsTab({
  invitations,
  session,
  onSelect,
  onChanged,
}: InvitationsTabProps) {
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sensitiveLink, setSensitiveLink] = useState<{
    email: string;
    url: string;
  } | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<InvitationSummary | null>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const revokeDialogRef = useRef<HTMLElement>(null);
  const revokeInputRef = useRef<HTMLInputElement>(null);

  useDialogFocus({
    active: revokeTarget !== null,
    containerRef: revokeDialogRef,
    initialFocusRef: revokeInputRef,
    onClose: closeRevoke,
  });

  function closeRevoke() {
    setRevokeTarget(null);
    setConfirmationText("");
  }

  async function resend(invitation: InvitationSummary) {
    setPendingAction(`resend:${invitation.invitation_id}`);
    setFeedback(null);
    setError(null);
    try {
      await resendInvitation(session.token, invitation.invitation_id);
      setFeedback(`Invitation resent to ${invitation.email}`);
      onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to resend invitation");
    } finally {
      setPendingAction(null);
    }
  }

  async function regenerate(invitation: InvitationSummary) {
    setPendingAction(`regenerate:${invitation.invitation_id}`);
    setFeedback(null);
    setError(null);
    setSensitiveLink(null);
    try {
      const result = await regenerateInvitation(session.token, invitation.invitation_id);
      const url = result.invitation.activation_url;
      if (url) {
        setSensitiveLink({ email: invitation.email, url });
      } else {
        setFeedback("Invitation regenerated, but no manual activation link was returned");
        onChanged?.();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to regenerate invitation");
    } finally {
      setPendingAction(null);
    }
  }

  async function copyLink() {
    if (!sensitiveLink) return;
    try {
      await navigator.clipboard.writeText(sensitiveLink.url);
      setFeedback("Activation link copied");
    } catch {
      setError("Unable to copy the activation link");
    }
  }

  async function revoke() {
    if (!revokeTarget || confirmationText !== "REVOKE") return;
    setPendingAction(`revoke:${revokeTarget.invitation_id}`);
    setFeedback(null);
    setError(null);
    try {
      await revokeInvitation(session.token, revokeTarget.invitation_id);
      setFeedback(`Invitation revoked for ${revokeTarget.email}`);
      setRevokeTarget(null);
      setConfirmationText("");
      onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to revoke invitation");
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <div>
      <div className="identity-table-scroll">
        <table aria-label="Invitations" className="identity-table">
        <thead>
          <tr>
            <th scope="col">Recipient</th>
            <th scope="col">Role</th>
            <th scope="col">Creator</th>
            <th scope="col">Delivery</th>
            <th scope="col">Status</th>
            <th scope="col">Created</th>
            <th scope="col">Expires</th>
          </tr>
        </thead>
        <tbody>
          {invitations.map((invitation) => (
            <tr key={invitation.invitation_id}>
              <td>
                <button
                  type="button"
                  className="identity-row-link"
                  onClick={() => onSelect?.(invitation)}
                >
                  {invitation.email}
                </button>
                {(session.role === "owner" || invitation.intended_role !== "admin") && (
                  <div className="identity-row-actions">
                  <button
                    type="button"
                    className="ghost-btn"
                    aria-label={`Resend invitation to ${invitation.email}`}
                    disabled={
                      pendingAction !== null ||
                      sensitiveLink !== null ||
                      invitation.status !== "pending"
                    }
                    onClick={() => resend(invitation)}
                  >
                    Resend
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    aria-label={`Regenerate link for ${invitation.email}`}
                    disabled={
                      pendingAction !== null ||
                      sensitiveLink !== null ||
                      invitation.status !== "pending"
                    }
                    onClick={() => regenerate(invitation)}
                  >
                    Regenerate link
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    aria-label={`Revoke invitation for ${invitation.email}`}
                    disabled={
                      pendingAction !== null ||
                      sensitiveLink !== null ||
                      invitation.status !== "pending"
                    }
                    onClick={() => {
                      setRevokeTarget(invitation);
                      setConfirmationText("");
                      setError(null);
                    }}
                  >
                    Revoke
                  </button>
                  </div>
                )}
              </td>
              <td>{invitation.intended_role}</td>
              <td>
                {invitation.creator?.display_name ??
                  invitation.creator?.email ??
                  "â€”"}
              </td>
              <td>
                {invitation.delivery_status}
                {invitation.delivery_error ? `: ${invitation.delivery_error}` : ""}
              </td>
              <td>{invitation.status}</td>
              <td>{displayDate(invitation.created_at)}</td>
              <td>{displayDate(invitation.expires_at)}</td>
            </tr>
          ))}
        </tbody>
        </table>
      </div>

      {sensitiveLink && (
        <section className="identity-sensitive-disclosure" aria-live="polite">
          <h3>Sensitive one-time activation link</h3>
          <p>
            Share only with {sensitiveLink.email}. This link is held only in the
            current screen state.
          </p>
          <code>{sensitiveLink.url}</code>
          <button type="button" onClick={copyLink}>
            Copy activation link
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={() => {
              setSensitiveLink(null);
              onChanged?.();
            }}
          >
            Hide activation link
          </button>
        </section>
      )}

      {revokeTarget && (
        <section
          ref={revokeDialogRef}
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="revoke-invitation-title"
        >
          <h3 id="revoke-invitation-title">Confirm invitation revocation</h3>
          <p>Type REVOKE to revoke the invitation for {revokeTarget.email}.</p>
          <label>
            Type REVOKE to confirm
            <input
              ref={revokeInputRef}
              aria-label="Type REVOKE to confirm"
              value={confirmationText}
              autoComplete="off"
              onChange={(event) => setConfirmationText(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={confirmationText !== "REVOKE" || pendingAction !== null}
            onClick={revoke}
          >
            Confirm revoke
          </button>
          <button type="button" className="ghost-btn" onClick={closeRevoke}>
            Cancel
          </button>
        </section>
      )}

      {feedback && <p role="status">{feedback}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
