"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { registerEventAction } from "./actions";
import {
  initialEventRegistrationState,
  type EventRegistrationState,
} from "./registration-state";

export function EventRegistrationForm({
  eventId,
  signedIn,
  alreadyRegistered,
}: {
  eventId: string;
  signedIn: boolean;
  alreadyRegistered: boolean;
}) {
  const [state, action, pending] = useActionState(
    registerEventAction,
    initialEventRegistrationState,
  ) as [EventRegistrationState, (formData: FormData) => void, boolean];

  if (!signedIn) {
    return (
      <Alert tone="info">
        Sign in to the member portal to register for this event.
      </Alert>
    );
  }

  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="eventId" value={eventId} />
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}
      <Button type="submit" disabled={pending || alreadyRegistered}>
        {pending
          ? "Registering…"
          : alreadyRegistered
            ? "Already registered"
            : "Register for this event"}
      </Button>
    </form>
  );
}
