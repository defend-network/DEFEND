"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  activateAccount,
  activationStatus,
  type ActivationStatus,
  type ActivationStatusResponse,
} from "@/lib/api";
import { Brand } from "./Brand";

type View = "loading" | "valid" | "success" | "error" | ActivationStatus;

const unavailableCopy: Record<Exclude<ActivationStatus, "pending">, [string, string]> = {
  expired: [
    "Invitation expired",
    "This account invitation is no longer available. Ask an administrator to send a new one.",
  ],
  consumed: [
    "Account already activated",
    "This invitation has already been used. Sign in with your account instead.",
  ],
  revoked: [
    "Invitation revoked",
    "This invitation is no longer available. Contact an administrator if you need access.",
  ],
  invalid: [
    "Invitation unavailable",
    "This activation link is invalid or no longer available.",
  ],
};

export default function AccountActivation() {
  const params = useParams<{ token?: string | string[] }>();
  const token = typeof params?.token === "string" ? params.token : "";
  const [view, setView] = useState<View>("loading");
  const [invitation, setInvitation] = useState<ActivationStatusResponse | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!token) {
      setView("invalid");
      return;
    }

    let active = true;
    activationStatus(token)
      .then((response) => {
        if (!active) return;
        setInvitation(response);
        setView(response.status === "pending" ? "valid" : response.status);
      })
      .catch(() => {
        if (active) setView("error");
      });

    return () => {
      active = false;
    };
  }, [token]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (password.length < 12) {
      setError("Use at least 12 characters for your password.");
      return;
    }
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await activateAccount(token, password);
      setPassword("");
      setConfirmation("");
      setView("success");
    } catch {
      setPassword("");
      setConfirmation("");
      setError("We could not activate this account. The invitation may no longer be available.");
    } finally {
      setSubmitting(false);
    }
  }

  const content = () => {
    if (view === "loading") {
      return <p aria-live="polite">Checking your invitation…</p>;
    }
    if (view === "success") {
      return <>
        <span className="eyebrow">Account ready</span>
        <h1>Activation complete</h1>
        <p>Your account is active. You can now return to DEFEND AI and sign in.</p>
        <a href="/">Return to DEFEND AI</a>
      </>;
    }
    if (view === "valid") {
      return <>
        <span className="eyebrow">Account activation</span>
        <h1>Create your password</h1>
        <p>
          {invitation?.display_name ? `Welcome, ${invitation.display_name}. ` : ""}
          Set a password to activate {invitation?.email ? `the account for ${invitation.email}` : "your account"}.
        </p>
        <form className="modal-form" onSubmit={submit}>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="New password"
            autoComplete="new-password"
            minLength={12}
            maxLength={512}
            required
            autoFocus
          />
          <input
            type="password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder="Confirm new password"
            autoComplete="new-password"
            minLength={12}
            maxLength={512}
            required
          />
          {error && <div className="admin-lock-err" role="alert">{error}</div>}
          <button className="modal-submit" type="submit" disabled={submitting}>
            {submitting ? "Activating…" : "Activate account"}
          </button>
        </form>
      </>;
    }
    if (view === "error") {
      return <>
        <span className="eyebrow">Unable to verify</span>
        <h1>Activation unavailable</h1>
        <p>We could not verify this invitation. Please try again or contact an administrator.</p>
      </>;
    }

    switch (view) {
      case "expired":
      case "consumed":
      case "revoked":
      case "invalid": {
        const [title, message] = unavailableCopy[view];
        return <>
          <span className="eyebrow">Account activation</span>
          <h1>{title}</h1>
          <p>{message}</p>
        </>;
      }
      default:
        return null;
    }
  };

  return (
    <main className="shell admin-lock">
      <div className="flag-bg" aria-hidden="true" />
      <header className="topbar"><Brand /></header>
      <section className="admin-lock-card">{content()}</section>
    </main>
  );
}
