"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createAllocationAction, createExpenseAction } from "./actions";
import {
  initialFinanceActionState,
  type FinanceActionState,
} from "./action-state";

function Result({ state }: { state: FinanceActionState }) {
  if (state.status === "idle") return null;
  return <div className="mt-3"><Alert tone={state.status === "success" ? "success" : "error"}>{state.message}</Alert></div>;
}

export function ExpenseForm({ chapters }: { chapters: Array<{ id: string; name: string }> }) {
  const [state, action, pending] = useActionState(createExpenseAction, initialFinanceActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Record expense</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="expense-vendor">Vendor</Label><Input id="expense-vendor" name="vendor" required /></div>
        <div className="grid gap-2"><Label htmlFor="expense-amount">Amount ($)</Label><Input id="expense-amount" name="amountDollars" type="number" min="0.01" step="0.01" required /></div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="expense-category">Category</Label>
          <select id="expense-category" name="category" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="operations">Operations</option><option value="events">Events</option><option value="programs">Programs</option><option value="facilities">Facilities</option><option value="legal">Legal</option><option value="general">General</option>
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="expense-chapter">Chapter</Label>
          <select id="expense-chapter" name="chapterId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="">Organization-wide</option>{chapters.map((chapter) => <option key={chapter.id} value={chapter.id}>{chapter.name}</option>)}
          </select>
        </div>
      </div>
      <div className="grid gap-2"><Label htmlFor="expense-date">Incurred at</Label><Input id="expense-date" name="incurredAt" type="datetime-local" required /></div>
      <div className="grid gap-2"><Label htmlFor="expense-paidby">Paid by</Label><Input id="expense-paidby" name="paidBy" /></div>
      <div className="grid gap-2"><Label htmlFor="expense-notes">Notes (encrypted)</Label><Textarea id="expense-notes" name="notes" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Recording…" : "Record expense"}</Button>
      <Result state={state} />
    </form>
  );
}

export function AllocationForm({ chapters }: { chapters: Array<{ id: string; name: string }> }) {
  const [state, action, pending] = useActionState(createAllocationAction, initialFinanceActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Chapter allocation</h2>
      <div className="grid gap-2"><Label htmlFor="allocation-chapter">Chapter</Label>
        <select id="allocation-chapter" name="chapterId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm" required>
          {chapters.map((chapter) => <option key={chapter.id} value={chapter.id}>{chapter.name}</option>)}
        </select>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="allocation-amount">Amount ($)</Label><Input id="allocation-amount" name="amountDollars" type="number" min="0.01" step="0.01" required /></div>
        <div className="grid gap-2"><Label htmlFor="allocation-period">Period</Label><Input id="allocation-period" name="period" placeholder="2026-11" /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="allocation-source">Source type</Label><Input id="allocation-source" name="sourceType" defaultValue="manual" /></div>
      <div className="grid gap-2"><Label htmlFor="allocation-notes">Notes</Label><Textarea id="allocation-notes" name="notes" /></div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Recording…" : "Record allocation"}</Button>
      <Result state={state} />
    </form>
  );
}
