"use client";

import { useState } from "react";
import { Brand } from "./Brand";
import { adminLogin } from "@/lib/api";
import {
  AdminSession,
  saveAdminSession,
} from "@/lib/adminAuth";

type Props = {
  onSuccess: (session: AdminSession) => void;
  eyebrow?: string;
  title?: string;
  description?: string;
  headerLabel?: string;
  headerHref?: string | null;
  backHref?: string | null;
  backLabel?: string | null;
};

export default function AdminLogin({
  onSuccess,
  eyebrow = "Restricted",
  title = "Admin access",
  description = "Enter your operator account to continue.",
  headerLabel = "DEFEND AI home",
  headerHref = "/",
  backHref = "/",
  backLabel = "← Back to DEFEND AI",
}: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await adminLogin(username.trim(), password);
      const now = Date.now();
      const session: AdminSession = {
        username: data.username,
        role: data.role,
        token: data.token,
        loggedInAt: new Date(now).toISOString(),
        expiresAt: new Date(now + data.expires_in * 1000).toISOString(),
      };
      saveAdminSession(session);
      onSuccess(session);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shell admin-lock">
      <div className="flag-bg" aria-hidden="true" />
      <header className="topbar">
        {headerHref ? (
          <a href={headerHref} aria-label={headerLabel}><Brand /></a>
        ) : (
          <span className="admin-lock-banner">{headerLabel}</span>
        )}
      </header>
      <form className="admin-lock-card" onSubmit={unlock}>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          autoComplete="username"
          autoFocus
          required
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete="current-password"
          required
        />
        {error && <div className="admin-lock-err">{error}</div>}
        <button type="submit" disabled={loading}>
          {loading ? "Checking…" : "Unlock"}
        </button>
        {backHref && backLabel !== null && <a href={backHref}>{backLabel}</a>}
      </form>
    </div>
  );
}
