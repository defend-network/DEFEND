"use client";

import { FormEvent, useState } from "react";

export function Login({onLogin}:{onLogin:(identifier:string,password:string)=>void|Promise<void>}) {
  const [identifier,setIdentifier] = useState("");
  const [password,setPassword] = useState("");
  const [error,setError] = useState<string|null>(null);
  async function submit(event:FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await onLogin(identifier,password);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign in failed");
    }
  }
  return <main className="login-shell">
    <section className="login-card">
      <div className="sun-mark" aria-hidden="true">SCS</div>
      <p className="eyebrow">Employee operations</p>
      <h1>Sunshine Climate Solutions</h1>
      <p className="muted">Secure access for owners and employees.</p>
      <form onSubmit={submit}>
        <label>Email or username<input autoComplete="username" value={identifier} onChange={e=>setIdentifier(e.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} /></label>
        {error && <p role="alert" className="login-error">{error}</p>}
        <button type="submit">Sign in</button>
      </form>
    </section>
  </main>;
}