import { and, count, desc, eq, like, or, type SQL } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { encryptPii, decryptPii } from "@/lib/security/pii";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  contacts,
  crmActivities,
  crmLeads,
  crmTasks,
  organizations,
} from "@/db/schema";

export async function listOrganizations(query = "") {
  const db = await getDb();
  const cleaned = query.trim();
  const pattern = `%${cleaned.slice(0, 120)}%`;
  const where = cleaned
    ? or(
        like(organizations.name, pattern),
        like(organizations.type, pattern),
        like(organizations.email, pattern),
      )
    : undefined;
  return db
    .select()
    .from(organizations)
    .where(where)
    .orderBy(desc(organizations.createdAt))
    .limit(100);
}

export async function listContacts(query = "") {
  const db = await getDb();
  const cleaned = query.trim();
  const pattern = `%${cleaned.slice(0, 120)}%`;
  const where = cleaned
    ? or(
        like(contacts.firstName, pattern),
        like(contacts.lastName, pattern),
        like(contacts.email, pattern),
        like(contacts.title, pattern),
      )
    : undefined;
  return db
    .select({
      id: contacts.id,
      firstName: contacts.firstName,
      lastName: contacts.lastName,
      title: contacts.title,
      email: contacts.email,
      status: contacts.status,
      organizationId: contacts.organizationId,
      createdAt: contacts.createdAt,
    })
    .from(contacts)
    .where(where)
    .orderBy(desc(contacts.createdAt))
    .limit(100);
}

export async function listLeads(input: { query?: string; stage?: string; type?: string } = {}) {
  const db = await getDb();
  const conditions: SQL[] = [];
  const cleaned = input.query?.trim();
  if (cleaned) {
    const pattern = `%${cleaned.slice(0, 120)}%`;
    conditions.push(
      or(
        like(crmLeads.title, pattern),
        like(crmLeads.source, pattern),
        like(crmLeads.type, pattern),
      ) as SQL,
    );
  }
  if (input.stage && input.stage !== "all") {
    conditions.push(eq(crmLeads.stage, input.stage));
  }
  if (input.type && input.type !== "all") {
    conditions.push(eq(crmLeads.type, input.type));
  }
  const where = conditions.length ? and(...conditions) : undefined;
  return db
    .select()
    .from(crmLeads)
    .where(where)
    .orderBy(desc(crmLeads.createdAt))
    .limit(100);
}

export async function createOrganization(input: {
  actor: ActorContext;
  name: string;
  type: string;
  website?: string;
  email?: string;
  phone?: string;
  address?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `org_${crypto.randomUUID()}`;
  await db.insert(organizations).values({
    id,
    name: input.name.trim(),
    type: input.type,
    website: input.website?.trim() || null,
    email: input.email?.trim().toLowerCase() || null,
    phoneEncrypted: input.phone?.trim() ? await encryptPii(input.phone.trim()) : null,
    address: input.address?.trim() || null,
    city: input.city?.trim() || null,
    state: input.state?.trim().toUpperCase() || null,
    postalCode: input.postalCode?.trim() || null,
    status: "active",
    notesEncrypted: input.notes?.trim() ? await encryptPii(input.notes.trim()) : null,
    createdBy: input.actor.userId,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "crm.organization.create",
    targetType: "organization",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { type: input.type },
  });
  return { ok: true as const, id };
}

export async function createContact(input: {
  actor: ActorContext;
  organizationId?: string | null;
  firstName: string;
  lastName: string;
  title?: string;
  email?: string;
  phone?: string;
  tags?: string;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `contact_${crypto.randomUUID()}`;
  await db.insert(contacts).values({
    id,
    organizationId: input.organizationId || null,
    firstName: input.firstName.trim(),
    lastName: input.lastName.trim(),
    title: input.title?.trim() || null,
    email: input.email?.trim().toLowerCase() || null,
    phoneEncrypted: input.phone?.trim() ? await encryptPii(input.phone.trim()) : null,
    tagsJson: JSON.stringify(
      input.tags ? input.tags.split(",").map((tag) => tag.trim()).filter(Boolean) : [],
    ),
    notesEncrypted: input.notes?.trim() ? await encryptPii(input.notes.trim()) : null,
    status: "active",
    ownerUserId: input.actor.userId,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "crm.contact.create",
    targetType: "contact",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { organizationId: input.organizationId ?? null },
  });
  return { ok: true as const, id };
}

export async function createLead(input: {
  actor: ActorContext;
  organizationId?: string | null;
  contactId?: string | null;
  type: string;
  title: string;
  source?: string;
  stage?: string;
  priority?: string;
  nextFollowUpAt?: Date | null;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `lead_${crypto.randomUUID()}`;
  await db.insert(crmLeads).values({
    id,
    organizationId: input.organizationId || null,
    contactId: input.contactId || null,
    type: input.type,
    title: input.title.trim(),
    source: input.source?.trim() || null,
    stage: input.stage || "new",
    priority: input.priority || "normal",
    assignedTo: input.actor.userId,
    nextFollowUpAt: input.nextFollowUpAt ?? null,
    notesEncrypted: input.notes?.trim() ? await encryptPii(input.notes.trim()) : null,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "crm.lead.create",
    targetType: "crm_lead",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { type: input.type, stage: input.stage ?? "new" },
  });
  return { ok: true as const, id };
}

export async function getLeadDetail(leadId: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(crmLeads)
    .where(eq(crmLeads.id, leadId))
    .limit(1);
  const lead = rows[0];
  if (!lead) return null;

  let organization:
    | (typeof organizations.$inferSelect & {
        phone?: string | null;
        notes?: string | null;
      })
    | null = null;
  if (lead.organizationId) {
    const orgRows = await db
      .select()
      .from(organizations)
      .where(eq(organizations.id, lead.organizationId))
      .limit(1);
    organization = orgRows[0] ?? null;
    if (organization?.phoneEncrypted) {
      organization = {
        ...organization,
        phone: await decryptPii(organization.phoneEncrypted).catch(() => null),
      };
    }
    if (organization?.notesEncrypted) {
      organization = {
        ...organization,
        notes: await decryptPii(organization.notesEncrypted).catch(() => null),
      };
    }
  }

  let contact:
    | (typeof contacts.$inferSelect & { phone?: string | null })
    | null = null;
  if (lead.contactId) {
    const contactRows = await db
      .select()
      .from(contacts)
      .where(eq(contacts.id, lead.contactId))
      .limit(1);
    contact = contactRows[0] ?? null;
    if (contact?.phoneEncrypted) {
      contact = {
        ...contact,
        phone: await decryptPii(contact.phoneEncrypted).catch(() => null),
      };
    }
  }

  const [activities, tasks] = await Promise.all([
    db
      .select()
      .from(crmActivities)
      .where(eq(crmActivities.leadId, leadId))
      .orderBy(desc(crmActivities.occurredAt))
      .limit(50),
    db
      .select()
      .from(crmTasks)
      .where(eq(crmTasks.leadId, leadId))
      .orderBy(crmTasks.status, crmTasks.dueAt)
      .limit(50),
  ]);

  const notes = lead.notesEncrypted
    ? await decryptPii(lead.notesEncrypted).catch(() => null)
    : null;

  return { lead: { ...lead, notes }, organization, contact, activities, tasks };
}

export async function updateLeadStage(input: {
  actor: ActorContext;
  leadId: string;
  stage: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const allowed = new Set(["new", "contacted", "qualified", "proposal", "won", "lost"]);
  if (!allowed.has(input.stage)) return { ok: false as const, error: "Invalid stage." };
  const db = await getDb();
  const rows = await db
    .select({ id: crmLeads.id, stage: crmLeads.stage })
    .from(crmLeads)
    .where(eq(crmLeads.id, input.leadId))
    .limit(1);
  const lead = rows[0];
  if (!lead) return { ok: false as const, error: "Lead not found." };
  await db
    .update(crmLeads)
    .set({ stage: input.stage, updatedAt: new Date() })
    .where(eq(crmLeads.id, lead.id));
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "crm.lead.stage",
    targetType: "crm_lead",
    targetId: lead.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { from: lead.stage, to: input.stage },
  });
  return { ok: true as const };
}

export async function addActivity(input: {
  actor: ActorContext;
  leadId: string;
  type: string;
  summary: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `activity_${crypto.randomUUID()}`;
  await db.insert(crmActivities).values({
    id,
    leadId: input.leadId,
    type: input.type,
    summary: input.summary.trim(),
    occurredAt: new Date(),
    createdBy: input.actor.userId,
    createdAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "crm.activity.add",
    targetType: "crm_lead",
    targetId: input.leadId,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { type: input.type },
  });
  return { ok: true as const };
}

export async function addTask(input: {
  actor: ActorContext;
  leadId: string;
  title: string;
  dueAt?: Date | null;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `task_${crypto.randomUUID()}`;
  await db.insert(crmTasks).values({
    id,
    leadId: input.leadId,
    title: input.title.trim(),
    dueAt: input.dueAt ?? null,
    assignedTo: input.actor.userId,
    status: "open",
    createdAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "crm.task.add",
    targetType: "crm_lead",
    targetId: input.leadId,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {},
  });
  return { ok: true as const };
}

export async function leadCounts() {
  const db = await getDb();
  const [open, wins] = await Promise.all([
    db
      .select({ value: count() })
      .from(crmLeads)
      .where(or(eq(crmLeads.stage, "new"), eq(crmLeads.stage, "contacted"), eq(crmLeads.stage, "qualified"), eq(crmLeads.stage, "proposal"))),
    db.select({ value: count() }).from(crmLeads).where(eq(crmLeads.stage, "won")),
  ]);
  return { open: open[0]?.value ?? 0, won: wins[0]?.value ?? 0 };
}
