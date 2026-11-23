"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

async function redirectTo(path: string) {
  const response = await fetch(path, { method: "POST" });
  const data = (await response.json()) as { url?: string; error?: string };
  if (!response.ok || !data.url) {
    throw new Error(data.error || "Unable to start billing.");
  }
  window.location.assign(data.url);
}

export function BillingActions({
  configured,
  hasCustomer,
}: {
  configured: boolean;
  hasCustomer: boolean;
}) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function start(path: string) {
    setError("");
    setPending(true);
    try {
      await redirectTo(path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Billing action failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid gap-3">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex flex-wrap gap-3">
        <Button
          type="button"
          disabled={!configured || pending}
          onClick={() => void start("/api/stripe/checkout")}
        >
          {pending ? "Opening…" : "Start test-mode subscription"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={!configured || !hasCustomer || pending}
          onClick={() => void start("/api/stripe/portal")}
        >
          Manage billing
        </Button>
      </div>
      {!configured ? (
        <p className="text-xs leading-5 text-slate-500">
          Stripe test-mode credentials are not configured. The button remains
          disabled; no fake success is shown.
        </p>
      ) : null}
    </div>
  );
}
