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
};

export default function AdminLogin({ onSuccess }: Props) {
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
        <a href="/" aria-label="DEFEND AI home"><Brand /></a>
      </header>
      <form className="admin-lock-card" onSubmit={unlock}>
        <span className="eyebrow">Restricted</span>
        <h1>Admin access</h1>
        <p>Enter your operator account to continue.</p>
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
        <a href="/">← Back to DEFEND AI</a>
      </form>
    </div>
  );
}
