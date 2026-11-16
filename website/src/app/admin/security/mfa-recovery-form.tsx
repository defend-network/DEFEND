"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { resetMfaAction } from "./actions";
import {
  initialMfaRecoveryState,
  type MfaRecoveryState,
} from "./state";

export function MfaRecoveryForm({ targetUserId }: { targetUserId: string }) {
  const [state, action, pending] = useActionState(
    resetMfaAction,
    initialMfaRecoveryState,
  ) as [MfaRecoveryState, (formData: FormData) => void, boolean];

  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="targetUserId" value={targetUserId} />
      <Input name="reason" placeholder="Reason for MFA reset" maxLength={200} required />
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}
      <Button type="submit" variant="danger" size="sm" disabled={pending}>
        {pending ? "Resetting…" : "Reset MFA and revoke sessions"}
      </Button>
    </form>
  );
}
