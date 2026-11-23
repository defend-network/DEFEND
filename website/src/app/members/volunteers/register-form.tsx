"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { registerVolunteerAction } from "./actions";
import {
  initialVolunteerRegistrationState,
  type VolunteerRegistrationState,
} from "./state";

export function VolunteerRegisterForm({
  opportunityId,
}: {
  opportunityId: string;
}) {
  const [state, action, pending] = useActionState(
    registerVolunteerAction,
    initialVolunteerRegistrationState,
  ) as [VolunteerRegistrationState, (formData: FormData) => void, boolean];

  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="opportunityId" value={opportunityId} />
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}
      <Button type="submit" variant="secondary" size="sm" disabled={pending}>
        {pending ? "Registering…" : "Register to volunteer"}
      </Button>
    </form>
  );
}
