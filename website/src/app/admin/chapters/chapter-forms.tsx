"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createChapterAction, updateChapterStatusAction } from "./actions";
import {
  initialChapterActionState,
  type ChapterActionState,
} from "./action-state";

function Result({ state }: { state: ChapterActionState }) {
  if (state.status === "idle") return null;
  return <div className="mt-3"><Alert tone={state.status === "success" ? "success" : "error"}>{state.message}</Alert></div>;
}

const statuses = ["operating", "in_development", "proposed", "inactive"];

export function ChapterForm() {
  const [state, action, pending] = useActionState(createChapterAction, initialChapterActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New chapter</h2>
      <div className="grid gap-2"><Label htmlFor="chapter-name">Name</Label><Input id="chapter-name" name="name" required /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="chapter-county">County</Label><Input id="chapter-county" name="county" required /></div>
        <div className="grid gap-2"><Label htmlFor="chapter-state">State</Label><Input id="chapter-state" name="state" maxLength={2} required /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="chapter-status">Status</Label>
        <select id="chapter-status" name="status" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          {statuses.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}
        </select>
      </div>
      <div className="grid gap-2"><Label htmlFor="chapter-contact">Contact email</Label><Input id="chapter-contact" name="contactEmail" type="email" /></div>
      <div className="grid gap-2"><Label htmlFor="chapter-description">Description</Label><Textarea id="chapter-description" name="description" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create chapter"}</Button>
      <Result state={state} />
    </form>
  );
}

export function ChapterStatusForm({ chapterId, status }: { chapterId: string; status: string }) {
  const [state, action, pending] = useActionState(updateChapterStatusAction, initialChapterActionState);
  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="chapterId" value={chapterId} />
      <select name="status" defaultValue={status} className="h-10 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
        {statuses.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
      </select>
      <Button type="submit" variant="secondary" size="sm" disabled={pending}>{pending ? "Updating…" : "Update status"}</Button>
      <Result state={state} />
    </form>
  );
}
