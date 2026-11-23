"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { assignRoleAction, revokeRoleAction } from "./actions";
import {
  initialSystemActionState,
  type SystemActionState,
} from "./action-state";

function Result({ state }: { state: SystemActionState }) {
  if (state.status === "idle") return null;
  return <div className="mt-3"><Alert tone={state.status === "success" ? "success" : "error"}>{state.message}</Alert></div>;
}

const assignableRoles = [
  "national_admin",
  "chapter_admin",
  "staff",
  "volunteer_coordinator",
  "member",
];

export function RoleAssignmentForm({
  users,
  chapters,
}: {
  users: Array<{ id: string; name: string; email: string }>;
  chapters: Array<{ id: string; name: string }>;
}) {
  const [state, action, pending] = useActionState(assignRoleAction, initialSystemActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Assign role</h2>
      <div className="grid gap-2">
        <Label htmlFor="role-user">User</Label>
        <select id="role-user" name="userId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm" required>
          {users.map((account) => <option key={account.id} value={account.id}>{account.name} · {account.email}</option>)}
        </select>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="role-key">Role</Label>
          <select id="role-key" name="roleKey" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            {assignableRoles.map((role) => <option key={role} value={role}>{role.replaceAll("_", " ")}</option>)}
          </select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="role-scope">Scope</Label>
          <select id="role-scope" name="scopeType" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="global">Global</option>
            <option value="chapter">Chapter</option>
          </select>
        </div>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="role-chapter">Chapter (if chapter-scoped)</Label>
        <select id="role-chapter" name="scopeId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="">None</option>
          {chapters.map((chapter) => <option key={chapter.id} value={chapter.id}>{chapter.name}</option>)}
        </select>
      </div>
      <Button type="submit" disabled={pending}>{pending ? "Assigning…" : "Assign role"}</Button>
      <Result state={state} />
    </form>
  );
}

export function RevokeRoleForm({ assignmentId }: { assignmentId: string }) {
  const [state, action, pending] = useActionState(revokeRoleAction, initialSystemActionState);
  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="assignmentId" value={assignmentId} />
      <Button type="submit" variant="danger" size="sm" disabled={pending}>{pending ? "Revoking…" : "Revoke"}</Button>
      <Result state={state} />
    </form>
  );
}
