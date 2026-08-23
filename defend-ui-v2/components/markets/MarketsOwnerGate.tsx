"use client";

import { useEffect, useState } from "react";
import { AdminSession, clearAdminSession, isOwner, loadAdminSession, saveAdminSession } from "@/lib/adminAuth";
import { marketsOwnerLogin, marketsOwnerLogout } from "@/lib/marketsOwnerApi";

function OwnerLoginForm({ onSuccess }: { onSuccess: (s: AdminSession) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await marketsOwnerLogin(username.trim(), password);
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shell admin-lock">
      <form className="admin-lock-card" onSubmit={unlock}>
        <span className="eyebrow">DEFENDmarkets</span>
        <h1>Owner workstation</h1>
        <p>Sign in with your owner account to inspect Markets.</p>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          autoComplete="username"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete="current-password"
        />
        {error ? <p className="admin-lock-error">{error}</p> : null}
        <button type="submit" disabled={loading || !username || !password}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function MarketsOwnerGate({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AdminSession | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const s = loadAdminSession();
    setSession(isOwner(s) ? s : null);
    setReady(true);
  }, []);

  function handleLogout() {
    void marketsOwnerLogout();
    clearAdminSession();
    setSession(null);
  }

  if (!ready) {
    return <div className="shell markets-loading">Loading…</div>;
  }

  if (!session) {
    return <OwnerLoginForm onSuccess={setSession} />;
  }

  return (
    <div className="markets-owner-session">
      <div className="markets-owner-bar">
        <span className="markets-owner-user">Owner · {session.username}</span>
        <button type="button" className="markets-owner-logout" onClick={handleLogout}>
          Sign out
        </button>
      </div>
      {children}
    </div>
  );
}
