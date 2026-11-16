"use client";

import { useActionState, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/input";
import {
  approveApplicationAction,
  denyApplicationAction,
  requestInfoAction,
} from "../actions";
import {
  initialApplicationActionState,
  type ApplicationActionState,
} from "../action-state";

function CopyLink({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 grid gap-2">
      <code className="break-all rounded-[var(--radius-control)] bg-navy-900 px-3 py-2 text-xs text-white">
        {value}
      </code>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
        }}
      >
        {copied ? "Copied" : "Copy link"}
      </Button>
    </div>
  );
}

function Result({ state }: { state: ApplicationActionState }) {
  if (state.status === "idle") return null;
  return (
    <div className="mt-4">
      <Alert tone={state.status === "success" ? "success" : "error"}>
        {state.message}
        {state.activationUrl ? <CopyLink value={state.activationUrl} /> : null}
        {state.updateUrl ? <CopyLink value={state.updateUrl} /> : null}
      </Alert>
    </div>
  );
}

export function ApplicationReviewPanel({
  applicationId,
  status,
}: {
  applicationId: string;
  status: string;
}) {
  const [approveState, approve, approvePending] = useActionState(
    approveApplicationAction,
    initialApplicationActionState,
  );
  const [denyState, deny, denyPending] = useActionState(
    denyApplicationAction,
    initialApplicationActionState,
  );
  const [infoState, requestInfo, infoPending] = useActionState(
    requestInfoAction,
    initialApplicationActionState,
  );

  const closed = status === "approved" || status === "denied" || status === "activated";

  return (
    <div className="grid gap-6">
      <form action={approve} className="rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
        <input type="hidden" name="applicationId" value={applicationId} />
        <h3 className="text-lg font-semibold">Approve application</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          Approval creates a single-use account invitation. It does not charge a
          card or mark the member as paid. Payment status remains separate.
        </p>
        <div className="mt-4 grid gap-2">
          <Label htmlFor="approve-notes">Review notes (optional)</Label>
          <Textarea id="approve-notes" name="notes" />
        </div>
        <div className="mt-4">
          <Button type="submit" disabled={closed || approvePending}>
            {approvePending ? "Approving…" : "Approve and create invitation"}
          </Button>
        </div>
        <Result state={approveState} />
      </form>

      <form action={requestInfo} className="rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
        <input type="hidden" name="applicationId" value={applicationId} />
        <h3 className="text-lg font-semibold">Request more information</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          Creates a one-time, expiring applicant update link. The application
          returns to review after the applicant submits changes.
        </p>
        <div className="mt-4 grid gap-2">
          <Label htmlFor="info-message">Message to applicant</Label>
          <Textarea id="info-message" name="message" required minLength={5} />
        </div>
        <div className="mt-4">
          <Button type="submit" variant="secondary" disabled={closed || infoPending}>
            {infoPending ? "Recording…" : "Request information"}
          </Button>
        </div>
        <Result state={infoState} />
      </form>

      <form action={deny} className="rounded-[var(--radius-card)] border border-error-700/20 bg-white p-5">
        <input type="hidden" name="applicationId" value={applicationId} />
        <h3 className="text-lg font-semibold text-error-700">Deny application</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          Denial is recorded with reviewer, timestamp, and notes. No payment can
          be requested for a denied applicant.
        </p>
        <div className="mt-4 grid gap-2">
          <Label htmlFor="deny-notes">Decision notes (restricted)</Label>
          <Textarea id="deny-notes" name="notes" />
        </div>
        <div className="mt-4">
          <Button type="submit" variant="danger" disabled={closed || denyPending}>
            {denyPending ? "Recording…" : "Deny application"}
          </Button>
        </div>
        <Result state={denyState} />
      </form>
    </div>
  );
}
