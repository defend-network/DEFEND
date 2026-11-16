"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { authClient } from "@/lib/auth/client";

export function VerificationNotice({ email }: { email: string }) {
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function send() {
    setPending(true);
    setMessage("");
    try {
      const result = await authClient.sendVerificationEmail({
        email,
        callbackURL: `${window.location.origin}/members?verified=1`,
      });
      setMessage(
        result.error
          ? result.error.message || "Unable to send the verification email."
          : "Verification email requested. Check the configured email transport or development outbox.",
      );
    } catch {
      setMessage("Unable to send the verification email.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid gap-3">
      {message ? <Alert tone="info">{message}</Alert> : null}
      <Button type="button" variant="secondary" size="sm" onClick={send} disabled={pending}>
        {pending ? "Sending…" : "Send verification email"}
      </Button>
    </div>
  );
}
