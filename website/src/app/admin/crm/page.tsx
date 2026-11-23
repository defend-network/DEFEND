import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import {
  leadCounts,
  listContacts,
  listLeads,
  listOrganizations,
} from "@/lib/crm/crm";
import { ContactForm, LeadForm, OrganizationForm } from "./crm-forms";

export const metadata: Metadata = {
  title: "CRM",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function CrmPage() {
  const { allowed } = await adminPageActor("crm.view");
  if (!allowed) return <AdminAccessDenied module="CRM" />;
  const [organizations, contacts, leads, counts] = await Promise.all([
    listOrganizations(),
    listContacts(),
    listLeads(),
    leadCounts(),
  ]);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Relationships
        </p>
        <h1 className="mt-3 text-3xl font-semibold">CRM</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Contacts, organizations, sponsors, property owners, contractors,
          suppliers, partners, and follow-up pipeline.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Organizations</p><CardTitle className="text-3xl">{organizations.length}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Contacts</p><CardTitle className="text-3xl">{contacts.length}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Open / won leads</p><CardTitle className="text-3xl">{counts.open} / {counts.won}</CardTitle></CardHeader></Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <OrganizationForm />
        <ContactForm organizations={organizations} />
        <LeadForm organizations={organizations} contacts={contacts} />
      </div>

      <Card>
        <CardHeader><CardTitle>Lead pipeline</CardTitle></CardHeader>
        <CardContent>
          {leads.length === 0 ? <p className="text-sm text-slate-500">No leads recorded.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr><th className="px-3 py-3">Lead</th><th className="px-3 py-3">Type</th><th className="px-3 py-3">Stage</th><th className="px-3 py-3">Priority</th><th className="px-3 py-3">Follow-up</th><th className="px-3 py-3" /></tr>
                </thead>
                <tbody>
                  {leads.map((lead) => (
                    <tr key={lead.id} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-3"><p className="font-semibold text-navy-900">{lead.title}</p><p className="text-xs text-slate-500">{lead.source || "—"}</p></td>
                      <td className="px-3 py-3 text-slate-600">{lead.type.replaceAll("_", " ")}</td>
                      <td className="px-3 py-3"><Badge variant={lead.stage === "won" ? "green" : lead.stage === "lost" ? "red" : "outline"}>{lead.stage}</Badge></td>
                      <td className="px-3 py-3 text-slate-600">{lead.priority}</td>
                      <td className="px-3 py-3 text-slate-600">{lead.nextFollowUpAt ? format(lead.nextFollowUpAt, "MMM d, yyyy") : "—"}</td>
                      <td className="px-3 py-3 text-right"><Link href={`/admin/crm/leads/${lead.id}`} className="text-sm font-semibold text-red-700 underline-offset-4 hover:underline">Open</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Organizations</CardTitle></CardHeader>
          <CardContent>
            {organizations.length === 0 ? <p className="text-sm text-slate-500">No organizations yet.</p> : (
              <ul className="grid gap-2 text-sm">
                {organizations.map((org) => (
                  <li key={org.id} className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <span><strong className="text-navy-900">{org.name}</strong><span className="ml-2 text-xs text-slate-500">{org.type.replaceAll("_", " ")}</span></span>
                    <span className="text-xs text-slate-500">{org.email || "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Contacts</CardTitle></CardHeader>
          <CardContent>
            {contacts.length === 0 ? <p className="text-sm text-slate-500">No contacts yet.</p> : (
              <ul className="grid gap-2 text-sm">
                {contacts.map((contact) => (
                  <li key={contact.id} className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <span><strong className="text-navy-900">{contact.firstName} {contact.lastName}</strong><span className="ml-2 text-xs text-slate-500">{contact.title || "—"}</span></span>
                    <span className="text-xs text-slate-500">{contact.email || "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
