"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TurnstileWidget } from "@/components/security/turnstile";
import { subscribeNewsletter } from "./actions";
import { initialNewsletterState } from "./state";

export function NewsletterForm() {
  const [state, action, pending] = useActionState(
    subscribeNewsletter,
    initialNewsletterState,
  ) as [typeof initialNewsletterState, (formData: FormData) => void, boolean];

  return (
    <form action={action} className="grid gap-5">
      <input type="text" name="website" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden="true" />
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}
      <div className="grid gap-2">
        <Label htmlFor="newsletter-email">Email address</Label>
        <Input id="newsletter-email" name="email" type="email" autoComplete="email" required />
      </div>
      <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
        <input type="checkbox" name="consent" required className="mt-1 size-4 rounded border-slate-300 accent-red-600" />
        <span>
          I consent to receive occasional DEFEND organizational updates. I can
          unsubscribe at any time. This is not a membership application.
        </span>
      </label>
      <TurnstileWidget />
      <Button type="submit" disabled={pending}>
        {pending ? "Subscribing…" : "Subscribe to updates"}
      </Button>
    </form>
  );
}
