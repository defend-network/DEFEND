import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { format } from "date-fns";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import { getLeadDetail } from "@/lib/crm/crm";
import {
  LeadActivityForm,
  LeadStageForm,
  LeadTaskForm,
} from "../../crm-forms";

export const metadata: Metadata = {
  title: "Lead Detail",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function LeadDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { allowed } = await adminPageActor("crm.view");
  if (!allowed) return <AdminAccessDenied module="CRM" />;
  const { id } = await params;
  const detail = await getLeadDetail(id);
  if (!detail) notFound();

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          CRM lead
        </p>
        <h1 className="mt-3 text-3xl font-semibold">{detail.lead.title}</h1>
        <p className="mt-2 text-sm text-slate-600">
          {detail.lead.type.replaceAll("_", " ")} · {detail.lead.stage} ·{" "}
          {detail.lead.priority} priority
        </p>
        <Link href="/admin/crm" className="mt-3 inline-block text-sm font-semibold text-red-700 underline-offset-4 hover:underline">
          Back to CRM
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="grid gap-6">
          <Card>
            <CardHeader><CardTitle>Lead details</CardTitle></CardHeader>
            <CardContent className="grid gap-3 text-sm text-slate-600">
              <p><strong className="text-navy-900">Source:</strong> {detail.lead.source || "—"}</p>
              <p><strong className="text-navy-900">Next follow-up:</strong> {detail.lead.nextFollowUpAt ? format(detail.lead.nextFollowUpAt, "MMM d, yyyy h:mm a") : "—"}</p>
              <p><strong className="text-navy-900">Notes:</strong> {detail.lead.notes || "—"}</p>
              {detail.organization ? (
                <div className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                  <p className="font-semibold text-navy-900">Organization</p>
                  <p>{detail.organization.name}</p>
                  <p className="text-xs">{detail.organization.email || "—"} · {detail.organization.phone || "no phone"}</p>
                </div>
              ) : null}
              {detail.contact ? (
                <div className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                  <p className="font-semibold text-navy-900">Contact</p>
                  <p>{detail.contact.firstName} {detail.contact.lastName}</p>
                  <p className="text-xs">{detail.contact.email || "—"} · {detail.contact.phone || "no phone"}</p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Activities</CardTitle></CardHeader>
            <CardContent>
              {detail.activities.length === 0 ? <p className="text-sm text-slate-500">No activities recorded.</p> : (
                <ul className="grid gap-2 text-sm">
                  {detail.activities.map((activity) => (
                    <li key={activity.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                      <p className="font-semibold capitalize text-navy-900">{activity.type.replaceAll("_", " ")}</p>
                      <p className="mt-1 text-slate-600">{activity.summary}</p>
                      <p className="mt-1 text-xs text-slate-500">{format(activity.occurredAt, "MMM d, yyyy h:mm a")}</p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Tasks</CardTitle></CardHeader>
            <CardContent>
              {detail.tasks.length === 0 ? <p className="text-sm text-slate-500">No tasks recorded.</p> : (
                <ul className="grid gap-2 text-sm">
                  {detail.tasks.map((task) => (
                    <li key={task.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3">
                      <span>{task.title}</span>
                      <span className="text-xs text-slate-500">
                        {task.status} · {task.dueAt ? format(task.dueAt, "MMM d, yyyy") : "no due date"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6">
          <Card>
            <CardHeader><CardTitle>Update stage</CardTitle></CardHeader>
            <CardContent><LeadStageForm leadId={detail.lead.id} stage={detail.lead.stage} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Record activity</CardTitle></CardHeader>
            <CardContent><LeadActivityForm leadId={detail.lead.id} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Add task</CardTitle></CardHeader>
            <CardContent><LeadTaskForm leadId={detail.lead.id} /></CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
