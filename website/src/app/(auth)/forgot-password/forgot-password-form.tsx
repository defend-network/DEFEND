"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authClient } from "@/lib/auth/client";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    setPending(true);
    try {
      const result = await authClient.requestPasswordReset({
        email: email.trim(),
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (result.error) {
        setError(result.error.message || "Unable to request a password reset.");
        return;
      }
      setMessage(
        "If an account exists for that address, a password reset link has been sent. Check the configured email transport or the development outbox.",
      );
    } catch {
      setError("Unable to request a password reset. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="grid gap-5" method="post" onSubmit={submit}>
      {message ? <Alert tone="success" role="status">{message}</Alert> : null}
      {error ? <Alert tone="error" role="alert">{error}</Alert> : null}
      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
      </div>
      <Button type="submit" disabled={pending}>
        {pending ? "Requestingâ€¦" : "Request password reset"}
      </Button>
    </form>
  );
}
