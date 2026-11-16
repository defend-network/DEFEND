import type { Metadata } from "next";
import { format } from "date-fns";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listChaptersBasic, listFinanceOverview } from "@/lib/finance/finance";
import { AllocationForm, ExpenseForm } from "./finance-forms";

export const metadata: Metadata = {
  title: "Finance",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function money(cents: number | null | undefined): string {
  return cents == null ? "—" : `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

export default async function FinancePage() {
  const [overview, chapters] = await Promise.all([
    listFinanceOverview(),
    listChaptersBasic(),
  ]);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Financial administration
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Finance</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Subscription status, payment events, recorded expenses, and chapter
          allocations. No revenue is fabricated.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Subscriptions</p><CardTitle className="text-3xl">{overview.subscriptions.length}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Payment events</p><CardTitle className="text-3xl">{overview.payments.length}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Recorded expenses</p><CardTitle className="text-3xl">{money(overview.totalExpensesCents)}</CardTitle></CardHeader></Card>
      </div>

      <Alert tone="warning">
        Donations and pledges are not active. No charitable solicitation or
        tax-deductible receipt is enabled. Stripe live charging remains disabled.
      </Alert>

      <div className="grid gap-5 xl:grid-cols-2">
        <ExpenseForm chapters={chapters} />
        <AllocationForm chapters={chapters} />
      </div>

      <Card>
        <CardHeader><CardTitle>Membership subscriptions</CardTitle></CardHeader>
        <CardContent>
          {overview.subscriptions.length === 0 ? <p className="text-sm text-slate-500">No subscriptions linked.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500"><tr><th className="px-3 py-3">Member</th><th className="px-3 py-3">Status</th><th className="px-3 py-3">Period end</th></tr></thead>
                <tbody>{overview.subscriptions.map((sub) => <tr key={sub.id} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3"><p className="font-semibold text-navy-900">{sub.memberName}</p><p className="text-xs text-slate-500">{sub.memberEmail}</p></td><td className="px-3 py-3"><Badge variant={sub.status === "active" ? "green" : "outline"}>{sub.status}</Badge></td><td className="px-3 py-3 text-slate-600">{sub.currentPeriodEnd ? format(sub.currentPeriodEnd, "MMM d, yyyy") : "—"}</td></tr>)}</tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Recent expenses</CardTitle></CardHeader>
          <CardContent>
            {overview.expenses.length === 0 ? <p className="text-sm text-slate-500">No expenses recorded.</p> : (
              <ul className="grid gap-2 text-sm">{overview.expenses.map((expense) => <li key={expense.id} className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border border-slate-200 p-3"><span><strong className="text-navy-900">{expense.vendor}</strong><span className="ml-2 text-xs text-slate-500">{expense.category}</span></span><span className="font-semibold text-navy-900">{money(expense.amountCents)}</span></li>)}</ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Chapter allocations</CardTitle></CardHeader>
          <CardContent>
            {overview.allocations.length === 0 ? <p className="text-sm text-slate-500">No allocations recorded.</p> : (
              <ul className="grid gap-2 text-sm">{overview.allocations.map((allocation) => <li key={allocation.id} className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border border-slate-200 p-3"><span><strong className="text-navy-900">{allocation.chapterName ?? "Chapter"}</strong><span className="ml-2 text-xs text-slate-500">{allocation.period || allocation.sourceType}</span></span><span className="font-semibold text-navy-900">{money(allocation.amountCents)}</span></li>)}</ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Payment events</CardTitle></CardHeader>
        <CardContent>
          {overview.payments.length === 0 ? <p className="text-sm text-slate-500">No payment events.</p> : (
            <ul className="grid gap-2 text-sm">{overview.payments.map((event) => <li key={event.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3"><span>{event.type}</span><span className="text-xs text-slate-500">{event.status} · {event.occurredAt ? format(event.occurredAt, "MMM d, yyyy h:mm a") : "—"}</span></li>)}</ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
