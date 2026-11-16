"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createProjectAction,
  createPropertyAction,
  createProposalAction,
} from "./actions";
import {
  initialFacilityActionState,
  type FacilityActionState,
} from "./action-state";

function Result({ state }: { state: FacilityActionState }) {
  if (state.status === "idle") return null;
  return <div className="mt-3"><Alert tone={state.status === "success" ? "success" : "error"}>{state.message}</Alert></div>;
}

export function PropertyForm({
  organizations,
  contacts,
}: {
  organizations: Array<{ id: string; name: string }>;
  contacts: Array<{ id: string; firstName: string; lastName: string }>;
}) {
  const [state, action, pending] = useActionState(createPropertyAction, initialFacilityActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New property lead</h2>
      <div className="grid gap-2"><Label htmlFor="property-address">Address</Label><Input id="property-address" name="address" required /></div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="grid gap-2"><Label htmlFor="property-city">City</Label><Input id="property-city" name="city" /></div>
        <div className="grid gap-2"><Label htmlFor="property-state">State</Label><Input id="property-state" name="state" maxLength={2} /></div>
        <div className="grid gap-2"><Label htmlFor="property-zip">ZIP</Label><Input id="property-zip" name="postalCode" /></div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="property-sqft">Building sqft</Label><Input id="property-sqft" name="buildingSqft" type="number" min={0} /></div>
        <div className="grid gap-2"><Label htmlFor="property-acreage">Acreage</Label><Input id="property-acreage" name="acreage" /></div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="property-owner">Owner name</Label><Input id="property-owner" name="ownerName" /></div>
        <div className="grid gap-2"><Label htmlFor="property-cost">Estimated cost ($)</Label><Input id="property-cost" name="estimatedCostDollars" type="number" min={0} /></div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="property-org">Organization</Label>
          <select id="property-org" name="organizationId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="">None</option>{organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="property-contact">Contact</Label>
          <select id="property-contact" name="contactId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="">None</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.firstName} {contact.lastName}</option>)}
          </select>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="property-listing">Listing URL</Label><Input id="property-listing" name="listingUrl" /></div>
        <div className="grid gap-2"><Label htmlFor="property-lease">Lease / donation</Label>
          <select id="property-lease" name="leaseOrDonation" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="unknown">Unknown</option><option value="lease">Lease</option><option value="donation">Donation</option><option value="purchase">Purchase</option>
          </select>
        </div>
      </div>
      <div className="grid gap-2"><Label htmlFor="property-notes">Notes (encrypted)</Label><Textarea id="property-notes" name="notes" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create property lead"}</Button>
      <Result state={state} />
    </form>
  );
}

export function ProjectForm({ properties }: { properties: Array<{ id: string; address: string }> }) {
  const [state, action, pending] = useActionState(createProjectAction, initialFacilityActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New facility project</h2>
      <div className="grid gap-2"><Label htmlFor="project-name">Project name</Label><Input id="project-name" name="name" required /></div>
      <div className="grid gap-2"><Label htmlFor="project-property">Property</Label>
        <select id="project-property" name="propertyLeadId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="">None</option>{properties.map((property) => <option key={property.id} value={property.id}>{property.address}</option>)}
        </select>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="project-stage">Stage</Label>
          <select id="project-stage" name="stage" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="concept">Concept</option><option value="research">Research</option><option value="site_visit">Site visit</option><option value="proposal">Proposal</option><option value="approved">Approved</option>
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="project-budget">Budget ($)</Label><Input id="project-budget" name="budgetDollars" type="number" min={0} /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="project-notes">Notes (encrypted)</Label><Textarea id="project-notes" name="notes" /></div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Creating…" : "Create project"}</Button>
      <Result state={state} />
    </form>
  );
}

export function ProposalForm({
  organizations,
  contacts,
}: {
  organizations: Array<{ id: string; name: string }>;
  contacts: Array<{ id: string; firstName: string; lastName: string }>;
}) {
  const [state, action, pending] = useActionState(createProposalAction, initialFacilityActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New partnership proposal</h2>
      <div className="grid gap-2"><Label htmlFor="proposal-title">Title</Label><Input id="proposal-title" name="title" required /></div>
      <div className="grid gap-2"><Label htmlFor="proposal-type">Type</Label>
        <select id="proposal-type" name="type" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="sponsorship">Sponsorship</option><option value="program">Program</option><option value="in_kind">In-kind</option><option value="property">Property</option><option value="other">Other</option>
        </select>
      </div>
      <div className="grid gap-2"><Label htmlFor="proposal-description">Description</Label><Textarea id="proposal-description" name="description" /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="proposal-org">Organization</Label>
          <select id="proposal-org" name="organizationId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="">None</option>{organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="proposal-amount">Amount ($)</Label><Input id="proposal-amount" name="amountDollars" type="number" min={0} /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="proposal-contact">Contact</Label>
        <select id="proposal-contact" name="contactId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="">None</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.firstName} {contact.lastName}</option>)}
        </select>
      </div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Creating…" : "Create proposal"}</Button>
      <Result state={state} />
    </form>
  );
}
