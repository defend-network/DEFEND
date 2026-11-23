"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  addActivityAction,
  addTaskAction,
  createContactAction,
  createLeadAction,
  createOrganizationAction,
  updateStageAction,
} from "./actions";
import { initialCrmActionState, type CrmActionState } from "./action-state";

function Result({ state }: { state: CrmActionState }) {
  if (state.status === "idle") return null;
  return (
    <div className="mt-3">
      <Alert tone={state.status === "success" ? "success" : "error"}>
        {state.message}
      </Alert>
    </div>
  );
}

const orgTypes = [
  "business", "nonprofit", "contractor", "supplier", "sponsor", "partner",
  "property_owner", "agency", "other",
];
const leadTypes = [
  "sponsor", "property", "contractor", "partner", "donor", "volunteer",
  "member_referral", "supplier", "other",
];
const stages = ["new", "contacted", "qualified", "proposal", "won", "lost"];

export function OrganizationForm() {
  const [state, action, pending] = useActionState(createOrganizationAction, initialCrmActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New organization</h2>
      <div className="grid gap-2"><Label htmlFor="org-name">Name</Label><Input id="org-name" name="name" required /></div>
      <div className="grid gap-2">
        <Label htmlFor="org-type">Type</Label>
        <select id="org-type" name="type" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          {orgTypes.map((type) => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}
        </select>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="org-email">Email</Label><Input id="org-email" name="email" type="email" /></div>
        <div className="grid gap-2"><Label htmlFor="org-phone">Phone</Label><Input id="org-phone" name="phone" type="tel" /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="org-website">Website</Label><Input id="org-website" name="website" /></div>
      <div className="grid gap-2"><Label htmlFor="org-address">Address</Label><Input id="org-address" name="address" /></div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="grid gap-2"><Label htmlFor="org-city">City</Label><Input id="org-city" name="city" /></div>
        <div className="grid gap-2"><Label htmlFor="org-state">State</Label><Input id="org-state" name="state" maxLength={2} /></div>
        <div className="grid gap-2"><Label htmlFor="org-zip">ZIP</Label><Input id="org-zip" name="postalCode" /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="org-notes">Notes (encrypted)</Label><Textarea id="org-notes" name="notes" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create organization"}</Button>
      <Result state={state} />
    </form>
  );
}

export function ContactForm({ organizations }: { organizations: Array<{ id: string; name: string }> }) {
  const [state, action, pending] = useActionState(createContactAction, initialCrmActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New contact</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="contact-first">First name</Label><Input id="contact-first" name="firstName" required /></div>
        <div className="grid gap-2"><Label htmlFor="contact-last">Last name</Label><Input id="contact-last" name="lastName" required /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="contact-org">Organization</Label>
        <select id="contact-org" name="organizationId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="">No organization</option>
          {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
        </select>
      </div>
      <div className="grid gap-2"><Label htmlFor="contact-title">Title</Label><Input id="contact-title" name="title" /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="contact-email">Email</Label><Input id="contact-email" name="email" type="email" /></div>
        <div className="grid gap-2"><Label htmlFor="contact-phone">Phone</Label><Input id="contact-phone" name="phone" type="tel" /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="contact-tags">Tags (comma separated)</Label><Input id="contact-tags" name="tags" /></div>
      <div className="grid gap-2"><Label htmlFor="contact-notes">Notes (encrypted)</Label><Textarea id="contact-notes" name="notes" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create contact"}</Button>
      <Result state={state} />
    </form>
  );
}

export function LeadForm({
  organizations,
  contacts,
}: {
  organizations: Array<{ id: string; name: string }>;
  contacts: Array<{ id: string; firstName: string; lastName: string }>;
}) {
  const [state, action, pending] = useActionState(createLeadAction, initialCrmActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New lead</h2>
      <div className="grid gap-2"><Label htmlFor="lead-title">Title</Label><Input id="lead-title" name="title" required /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="lead-type">Type</Label>
          <select id="lead-type" name="type" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            {leadTypes.map((type) => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="lead-stage">Stage</Label>
          <select id="lead-stage" name="stage" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            {stages.map((stage) => <option key={stage} value={stage}>{stage}</option>)}
          </select>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="lead-org">Organization</Label>
          <select id="lead-org" name="organizationId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="">None</option>
            {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
          </select>
        </div>
        <div className="grid gap-2"><Label htmlFor="lead-contact">Contact</Label>
          <select id="lead-contact" name="contactId" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="">None</option>
            {contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.firstName} {contact.lastName}</option>)}
          </select>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="lead-source">Source</Label><Input id="lead-source" name="source" /></div>
        <div className="grid gap-2"><Label htmlFor="lead-follow">Next follow-up</Label><Input id="lead-follow" name="nextFollowUpAt" type="datetime-local" /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="lead-priority">Priority</Label>
        <select id="lead-priority" name="priority" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="normal">Normal</option><option value="high">High</option><option value="low">Low</option>
        </select>
      </div>
      <div className="grid gap-2"><Label htmlFor="lead-notes">Notes (encrypted)</Label><Textarea id="lead-notes" name="notes" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create lead"}</Button>
      <Result state={state} />
    </form>
  );
}

export function LeadStageForm({ leadId, stage }: { leadId: string; stage: string }) {
  const [state, action, pending] = useActionState(updateStageAction, initialCrmActionState);
  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="leadId" value={leadId} />
      <select name="stage" defaultValue={stage} className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
        {stages.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Updating…" : "Update stage"}</Button>
      <Result state={state} />
    </form>
  );
}

export function LeadActivityForm({ leadId }: { leadId: string }) {
  const [state, action, pending] = useActionState(addActivityAction, initialCrmActionState);
  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="leadId" value={leadId} />
      <select name="type" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
        {["note", "call", "email", "meeting", "site_visit"].map((type) => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}
      </select>
      <Textarea name="summary" placeholder="Activity summary" required />
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Recording…" : "Add activity"}</Button>
      <Result state={state} />
    </form>
  );
}

export function LeadTaskForm({ leadId }: { leadId: string }) {
  const [state, action, pending] = useActionState(addTaskAction, initialCrmActionState);
  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="leadId" value={leadId} />
      <Input name="title" placeholder="Task title" required />
      <Input name="dueAt" type="datetime-local" />
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Creating…" : "Add task"}</Button>
      <Result state={state} />
    </form>
  );
}
