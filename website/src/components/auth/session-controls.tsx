"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { authClient } from "@/lib/auth/client";

export function SessionControls() {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function revokeOthers() {
    setPending(true);
    setMessage("");
    setError("");
    try {
      const result = await authClient.revokeOtherSessions();
      if (result.error) {
        setError(result.error.message || "Unable to sign out other sessions.");
        return;
      }
      setMessage("Other sessions have been signed out.");
    } catch {
      setError("Unable to sign out other sessions. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid gap-3">
      {message ? <Alert tone="success">{message}</Alert> : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Button
        type="button"
        variant="secondary"
        onClick={revokeOthers}
        disabled={pending}
      >
        {pending ? "Signing out other sessions…" : "Sign out other sessions"}
      </Button>
    </div>
  );
}
