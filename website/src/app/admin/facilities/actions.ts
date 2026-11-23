"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import {
  createFacilityProject,
  createPartnershipProposal,
  createPropertyLead,
} from "@/lib/facilities/facilities";
import type { FacilityActionState } from "./action-state";

async function facilityActor() {
  const actor = await getActor();
  if (!actor || !can(actor, "facilities.manage")) {
    throw new Error("MFA-verified facilities access is required.");
  }
  return actor;
}

function value(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

export async function createPropertyAction(
  _previous: FacilityActionState,
  formData: FormData,
): Promise<FacilityActionState> {
  try {
    const actor = await facilityActor();
    const address = value(formData, "address");
    if (!address) return { status: "error", message: "Enter an address." };
    const sqft = Number(formData.get("buildingSqft") ?? "");
    const cost = Number(formData.get("estimatedCostDollars") ?? "");
    const context = await requestAuditContext();
    await createPropertyLead({
      actor,
      organizationId: value(formData, "organizationId") || null,
      contactId: value(formData, "contactId") || null,
      address,
      city: value(formData, "city"),
      state: value(formData, "state"),
      postalCode: value(formData, "postalCode"),
      buildingSqft: Number.isFinite(sqft) && sqft > 0 ? sqft : null,
      acreage: value(formData, "acreage"),
      ownerName: value(formData, "ownerName"),
      listingUrl: value(formData, "listingUrl"),
      leaseOrDonation: value(formData, "leaseOrDonation") || "unknown",
      estimatedCostCents:
        Number.isFinite(cost) && cost > 0 ? Math.round(cost * 100) : null,
      notes: value(formData, "notes"),
      ...context,
    });
    revalidatePath("/admin/facilities");
    return { status: "success", message: "Property lead created." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Property creation failed." };
  }
}

export async function createProjectAction(
  _previous: FacilityActionState,
  formData: FormData,
): Promise<FacilityActionState> {
  try {
    const actor = await facilityActor();
    const name = value(formData, "name");
    if (!name) return { status: "error", message: "Enter a project name." };
    const budget = Number(formData.get("budgetDollars") ?? "");
    const context = await requestAuditContext();
    await createFacilityProject({
      actor,
      propertyLeadId: value(formData, "propertyLeadId") || null,
      name,
      stage: value(formData, "stage") || "concept",
      budgetCents: Number.isFinite(budget) && budget > 0 ? Math.round(budget * 100) : null,
      notes: value(formData, "notes"),
      ...context,
    });
    revalidatePath("/admin/facilities");
    return { status: "success", message: "Facility project created." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Project creation failed." };
  }
}

export async function createProposalAction(
  _previous: FacilityActionState,
  formData: FormData,
): Promise<FacilityActionState> {
  try {
    const actor = await facilityActor();
    const title = value(formData, "title");
    if (!title) return { status: "error", message: "Enter a proposal title." };
    const amount = Number(formData.get("amountDollars") ?? "");
    const context = await requestAuditContext();
    await createPartnershipProposal({
      actor,
      organizationId: value(formData, "organizationId") || null,
      contactId: value(formData, "contactId") || null,
      type: value(formData, "type") || "other",
      title,
      description: value(formData, "description"),
      amountCents: Number.isFinite(amount) && amount > 0 ? Math.round(amount * 100) : null,
      ...context,
    });
    revalidatePath("/admin/facilities");
    return { status: "success", message: "Partnership proposal created." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Proposal creation failed." };
  }
}
