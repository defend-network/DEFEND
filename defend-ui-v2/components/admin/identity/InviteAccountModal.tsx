"use client";

import { useState } from "react";

import type { AdminSession } from "@/lib/adminAuth";
import {
  createAccount,
  type CreateAccountResponse,
  type CreateAccountInput,
} from "@/lib/identityApi";

type InviteAccountModalProps = {
  session: AdminSession;
  onClose: () => void;
  onCreated: (result: CreateAccountResponse) => void;
};

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to create account";
}

export function InviteAccountModal({
  session,
  onClose,
  onCreated,
}: InviteAccountModalProps) {
  const [input, setInput] = useState<CreateAccountInput>({
    display_name: "",
    email: "",
    role: "user",
  });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreateAccountResponse | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const activationUrl = created?.invitation.activation_url ?? null;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await createAccount(session.token, input);
      setCreated(result);
      setFeedback("Account and invitation created");
      onCreated(result);
    } catch (caught) {
      setError(messageFrom(caught));
    } finally {
      setCreating(false);
    }
  }

  async function copyLink() {
    if (!activationUrl) return;
    try {
      await navigator.clipboard.writeText(activationUrl);
      setFeedback("Activation link copied");
    } catch {
      setError("Unable to copy the activation link");
    }
  }

  return (
    <div className="identity-modal-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="invite-account-title"
        className="admin-card identity-modal"
      >
        <header className="identity-detail-header">
          <div>
            <span className="eyebrow">Account invitation</span>
            <h2 id="invite-account-title">Create account</h2>
          </div>
          <button type="button" className="ghost-btn" onClick={onClose}>
            Close
          </button>
        </header>

        {!created ? (
          <form onSubmit={submit} className="identity-action-form">
            <label>
              Display name
              <input
                value={input.display_name}
                maxLength={160}
                required
                onChange={(event) =>
                  setInput((current) => ({
                    ...current,
                    display_name: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Email address
              <input
                type="email"
                value={input.email}
                maxLength={320}
                required
                onChange={(event) =>
                  setInput((current) => ({
                    ...current,
                    email: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Role
              <select
                value={input.role}
                onChange={(event) =>
                  setInput((current) => ({
                    ...current,
                    role: event.target.value === "admin" ? "admin" : "user",
                  }))
                }
              >
                <option value="user">End user</option>
                {session.role === "owner" && (
                  <option value="admin">Administrator</option>
                )}
              </select>
            </label>
            <button type="submit" disabled={creating}>
              {creating ? "Creating..." : "Create account and invitation"}
            </button>
          </form>
        ) : (
          <div className="identity-sensitive-disclosure">
            <h3>Sensitive one-time activation link</h3>
            <p>
              Share only with {created.account.email}. This link is not retained in
              this screen after it is closed.
            </p>
            {activationUrl ? (
              <>
                <code>{activationUrl}</code>
                <button type="button" onClick={copyLink}>
                  Copy activation link
                </button>
              </>
            ) : (
              <p>The account was created, but no manual activation link was returned.</p>
            )}
          </div>
        )}

        {feedback && <p role="status">{feedback}</p>}
        {error && <p role="alert">{error}</p>}
      </section>
    </div>
  );
}
