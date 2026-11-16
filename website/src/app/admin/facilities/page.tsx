import type { Metadata } from "next";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listContacts, listOrganizations } from "@/lib/crm/crm";
import {
  listFacilityProjects,
  listPartnershipProposals,
  listPropertyLeads,
} from "@/lib/facilities/facilities";
import { ProjectForm, PropertyForm, ProposalForm } from "./facility-forms";

export const metadata: Metadata = {
  title: "Facilities",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function money(cents: number | null): string {
  return cents == null ? "—" : `$${(cents / 100).toLocaleString()}`;
}

export default async function FacilitiesPage() {
  const [organizations, contacts, properties, projects, proposals] =
    await Promise.all([
      listOrganizations(),
      listContacts(),
      listPropertyLeads(),
      listFacilityProjects(),
      listPartnershipProposals(),
    ]);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Internal operations
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Facilities and property</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Property leads, site research, facility projects, and partnership
          proposals. This information is internal and is never exposed publicly.
        </p>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <PropertyForm organizations={organizations} contacts={contacts} />
        <ProjectForm properties={properties} />
        <ProposalForm organizations={organizations} contacts={contacts} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Property leads</CardTitle></CardHeader>
          <CardContent>
            {properties.length === 0 ? <p className="text-sm text-slate-500">No property leads.</p> : (
              <ul className="grid gap-2 text-sm">
                {properties.map((property) => (
                  <li key={property.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <p className="font-semibold text-navy-900">{property.address}</p>
                    <p className="text-xs text-slate-500">
                      {[property.city, property.state].filter(Boolean).join(", ")} · {property.leaseOrDonation} · {property.status}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {property.buildingSqft ? `${property.buildingSqft.toLocaleString()} sqft · ` : ""}
                      {money(property.estimatedCostCents)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Facility projects</CardTitle></CardHeader>
          <CardContent>
            {projects.length === 0 ? <p className="text-sm text-slate-500">No facility projects.</p> : (
              <ul className="grid gap-2 text-sm">
                {projects.map((project) => (
                  <li key={project.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <p className="font-semibold text-navy-900">{project.name}</p>
                    <p className="text-xs text-slate-500">{project.stage} · {project.status} · {money(project.budgetCents)}</p>
                    {project.targetDate ? <p className="text-xs text-slate-500">Target {format(project.targetDate, "MMM d, yyyy")}</p> : null}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Partnership proposals</CardTitle></CardHeader>
        <CardContent>
          {proposals.length === 0 ? <p className="text-sm text-slate-500">No proposals.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr><th className="px-3 py-3">Proposal</th><th className="px-3 py-3">Type</th><th className="px-3 py-3">Amount</th><th className="px-3 py-3">Status</th></tr>
                </thead>
                <tbody>
                  {proposals.map((proposal) => (
                    <tr key={proposal.id} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-3 font-semibold text-navy-900">{proposal.title}</td>
                      <td className="px-3 py-3 text-slate-600">{proposal.type.replaceAll("_", " ")}</td>
                      <td className="px-3 py-3 text-slate-600">{money(proposal.amountCents)}</td>
                      <td className="px-3 py-3"><Badge variant="outline">{proposal.status}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
