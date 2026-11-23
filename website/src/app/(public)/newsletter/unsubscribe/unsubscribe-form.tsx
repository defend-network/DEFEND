"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { unsubscribeNewsletter } from "../actions";
import { initialUnsubscribeState } from "../state";

export function UnsubscribeForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(
    unsubscribeNewsletter,
    initialUnsubscribeState,
  ) as [typeof initialUnsubscribeState, (formData: FormData) => void, boolean];

  return (
    <form action={action} className="grid gap-4">
      <input type="hidden" name="token" value={token} />
      {state.status === "success" ? (
        <Alert tone="success" role="status">
          {state.message}
        </Alert>
      ) : null}
      {state.status === "error" ? (
        <Alert tone="error" role="alert">
          {state.message}
        </Alert>
      ) : null}
      {state.status === "success" ? null : (
        <Button type="submit" variant="secondary" disabled={pending}>
          {pending ? "Updating…" : "Confirm unsubscribe"}
        </Button>
      )}
    </form>
  );
}
