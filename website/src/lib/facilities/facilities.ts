import { desc } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { encryptPii, decryptPii } from "@/lib/security/pii";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  facilityProjects,
  partnershipProposals,
  propertyLeads,
} from "@/db/schema";

export async function listPropertyLeads() {
  const db = await getDb();
  const rows = await db
    .select()
    .from(propertyLeads)
    .orderBy(desc(propertyLeads.createdAt))
    .limit(100);
  return Promise.all(
    rows.map(async (row) => ({
      ...row,
      notes: row.notesEncrypted
        ? await decryptPii(row.notesEncrypted).catch(() => null)
        : null,
    })),
  );
}

export async function listFacilityProjects() {
  const db = await getDb();
  return db
    .select()
    .from(facilityProjects)
    .orderBy(desc(facilityProjects.createdAt))
    .limit(100);
}

export async function listPartnershipProposals() {
  const db = await getDb();
  return db
    .select()
    .from(partnershipProposals)
    .orderBy(desc(partnershipProposals.createdAt))
    .limit(100);
}

export async function createPropertyLead(input: {
  actor: ActorContext;
  organizationId?: string | null;
  contactId?: string | null;
  address: string;
  city?: string;
  state?: string;
  postalCode?: string;
  buildingSqft?: number | null;
  acreage?: string;
  ownerName?: string;
  listingUrl?: string;
  leaseOrDonation?: string;
  estimatedCostCents?: number | null;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `property_${crypto.randomUUID()}`;
  await db.insert(propertyLeads).values({
    id,
    organizationId: input.organizationId || null,
    contactId: input.contactId || null,
    address: input.address.trim(),
    city: input.city?.trim() || null,
    state: input.state?.trim().toUpperCase() || null,
    postalCode: input.postalCode?.trim() || null,
    buildingSqft: input.buildingSqft ?? null,
    acreage: input.acreage?.trim() || null,
    ownerName: input.ownerName?.trim() || null,
    listingUrl: input.listingUrl?.trim() || null,
    leaseOrDonation: input.leaseOrDonation || "unknown",
    status: "new",
    estimatedCostCents: input.estimatedCostCents ?? null,
    notesEncrypted: input.notes?.trim() ? await encryptPii(input.notes.trim()) : null,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "facility.property.create",
    targetType: "property_lead",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { leaseOrDonation: input.leaseOrDonation ?? "unknown" },
  });
  return { ok: true as const, id };
}

export async function createFacilityProject(input: {
  actor: ActorContext;
  propertyLeadId?: string | null;
  name: string;
  stage?: string;
  budgetCents?: number | null;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `facility_${crypto.randomUUID()}`;
  await db.insert(facilityProjects).values({
    id,
    propertyLeadId: input.propertyLeadId || null,
    name: input.name.trim(),
    stage: input.stage || "concept",
    budgetCents: input.budgetCents ?? null,
    status: "active",
    notesEncrypted: input.notes?.trim() ? await encryptPii(input.notes.trim()) : null,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "facility.project.create",
    targetType: "facility_project",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {},
  });
  return { ok: true as const, id };
}

export async function createPartnershipProposal(input: {
  actor: ActorContext;
  organizationId?: string | null;
  contactId?: string | null;
  type?: string;
  title: string;
  description?: string;
  amountCents?: number | null;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `proposal_${crypto.randomUUID()}`;
  await db.insert(partnershipProposals).values({
    id,
    organizationId: input.organizationId || null,
    contactId: input.contactId || null,
    type: input.type || "other",
    title: input.title.trim(),
    description: input.description?.trim() || "",
    amountCents: input.amountCents ?? null,
    status: "draft",
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "partnership.proposal.create",
    targetType: "partnership_proposal",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { type: input.type ?? "other" },
  });
  return { ok: true as const, id };
}
