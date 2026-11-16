"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createProgramAction } from "./actions";
import {
  initialProgramActionState,
  type ProgramActionState,
} from "./action-state";

export function ProgramForm() {
  const [state, action, pending] = useActionState(
    createProgramAction,
    initialProgramActionState,
  ) as [ProgramActionState, (formData: FormData) => void, boolean];

  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New program</h2>
      <div className="grid gap-2"><Label htmlFor="program-title">Title</Label><Input id="program-title" name="title" required /></div>
      <div className="grid gap-2"><Label htmlFor="program-summary">Summary</Label><Input id="program-summary" name="summary" /></div>
      <div className="grid gap-2"><Label htmlFor="program-description">Description</Label><Textarea id="program-description" name="description" /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="program-status">Status</Label>
          <select id="program-status" name="status" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="planned">Planned</option><option value="in_development">In development</option><option value="operating">Operating</option><option value="proposed">Proposed</option>
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="program-capacity">Capacity (optional)</Label><Input id="program-capacity" name="capacity" type="number" min={1} /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="program-fee">Program fee ($, optional)</Label><Input id="program-fee" name="feeDollars" type="number" min={0} step="0.01" /></div>
      <div className="grid gap-2"><Label htmlFor="program-eligibility">Eligibility</Label><Textarea id="program-eligibility" name="eligibility" placeholder="Adults, members, family participation, etc." /></div>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" name="familyFriendly" className="size-4 accent-red-600" />
        Family-friendly program
      </label>
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create program"}</Button>
    </form>
  );
}
