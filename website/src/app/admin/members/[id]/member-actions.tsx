"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  assignChapterAction,
  updateMemberStatusAction,
} from "../actions";
import {
  initialMemberActionState,
  type MemberActionState,
} from "../action-state";

function Result({ state }: { state: MemberActionState }) {
  if (state.status === "idle") return null;
  return (
    <div className="mt-3">
      <Alert tone={state.status === "success" ? "success" : "error"}>
        {state.message}
      </Alert>
    </div>
  );
}

export function MemberStatusForm({
  userId,
  currentStatus,
}: {
  userId: string;
  currentStatus: string;
}) {
  const [state, action, pending] = useActionState(
    updateMemberStatusAction,
    initialMemberActionState,
  );

  return (
    <form action={action} className="grid gap-4">
      <input type="hidden" name="userId" value={userId} />
      <div className="grid gap-2">
        <Label htmlFor="status">Membership standing</Label>
        <select
          id="status"
          name="status"
          defaultValue={currentStatus}
          className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="founding_access">Founding access — not paid</option>
          <option value="pending_payment">Pending payment</option>
          <option value="active">Active — dues verified</option>
          <option value="grace">Grace</option>
          <option value="lapsed">Lapsed</option>
          <option value="cancelled">Cancelled</option>
          <option value="suspended">Suspended</option>
        </select>
        <p className="text-xs leading-5 text-slate-500">
          “Active” indicates verified dues and should not be selected merely to
          grant portal access. Use “Founding access — not paid” while billing is
          inactive.
        </p>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="reason">Reason (recorded in history)</Label>
        <Input id="reason" name="reason" maxLength={200} />
      </div>
      <Button type="submit" disabled={pending}>
        {pending ? "Updating…" : "Update standing"}
      </Button>
      <Result state={state} />
    </form>
  );
}

export function ChapterAssignmentForm({
  userId,
  currentChapterId,
  chapters,
}: {
  userId: string;
  currentChapterId: string | null;
  chapters: Array<{ id: string; name: string; status: string }>;
}) {
  const [state, action, pending] = useActionState(
    assignChapterAction,
    initialMemberActionState,
  );

  return (
    <form action={action} className="grid gap-4">
      <input type="hidden" name="userId" value={userId} />
      <div className="grid gap-2">
        <Label htmlFor="chapterId">Chapter assignment</Label>
        <select
          id="chapterId"
          name="chapterId"
          defaultValue={currentChapterId ?? ""}
          className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm"
        >
          {chapters.map((chapter) => (
            <option key={chapter.id} value={chapter.id}>
              {chapter.name} — {chapter.status.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </div>
      <Button type="submit" variant="secondary" disabled={pending}>
        {pending ? "Assigning…" : "Assign chapter"}
      </Button>
      <Result state={state} />
    </form>
  );
}
