"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import {
  addActivity,
  addTask,
  createContact,
  createLead,
  createOrganization,
  updateLeadStage,
} from "@/lib/crm/crm";
import type { CrmActionState } from "./action-state";

async function crmActor() {
  const actor = await getActor();
  if (!actor || !can(actor, "crm.manage")) {
    throw new Error("MFA-verified CRM access is required.");
  }
  return actor;
}

function formString(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

export async function createOrganizationAction(
  _previous: CrmActionState,
  formData: FormData,
): Promise<CrmActionState> {
  try {
    const actor = await crmActor();
    const name = formString(formData, "name");
    if (!name) return { status: "error", message: "Enter an organization name." };
    const context = await requestAuditContext();
    await createOrganization({
      actor,
      name,
      type: formString(formData, "type") || "other",
      website: formString(formData, "website"),
      email: formString(formData, "email"),
      phone: formString(formData, "phone"),
      address: formString(formData, "address"),
      city: formString(formData, "city"),
      state: formString(formData, "state"),
      postalCode: formString(formData, "postalCode"),
      notes: formString(formData, "notes"),
      ...context,
    });
    revalidatePath("/admin/crm");
    return { status: "success", message: "Organization created." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Organization creation failed.",
    };
  }
}

export async function createContactAction(
  _previous: CrmActionState,
  formData: FormData,
): Promise<CrmActionState> {
  try {
    const actor = await crmActor();
    const firstName = formString(formData, "firstName");
    const lastName = formString(formData, "lastName");
    if (!firstName || !lastName) {
      return { status: "error", message: "Enter a first and last name." };
    }
    const context = await requestAuditContext();
    await createContact({
      actor,
      organizationId: formString(formData, "organizationId") || null,
      firstName,
      lastName,
      title: formString(formData, "title"),
      email: formString(formData, "email"),
      phone: formString(formData, "phone"),
      tags: formString(formData, "tags"),
      notes: formString(formData, "notes"),
      ...context,
    });
    revalidatePath("/admin/crm");
    return { status: "success", message: "Contact created." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Contact creation failed.",
    };
  }
}

export async function createLeadAction(
  _previous: CrmActionState,
  formData: FormData,
): Promise<CrmActionState> {
  try {
    const actor = await crmActor();
    const title = formString(formData, "title");
    if (!title) return { status: "error", message: "Enter a lead title." };
    const followUp = formString(formData, "nextFollowUpAt");
    const context = await requestAuditContext();
    await createLead({
      actor,
      organizationId: formString(formData, "organizationId") || null,
      contactId: formString(formData, "contactId") || null,
      type: formString(formData, "type") || "other",
      title,
      source: formString(formData, "source"),
      stage: formString(formData, "stage") || "new",
      priority: formString(formData, "priority") || "normal",
      nextFollowUpAt: followUp ? new Date(followUp) : null,
      notes: formString(formData, "notes"),
      ...context,
    });
    revalidatePath("/admin/crm");
    return { status: "success", message: "Lead created." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Lead creation failed.",
    };
  }
}

export async function updateStageAction(
  _previous: CrmActionState,
  formData: FormData,
): Promise<CrmActionState> {
  try {
    const actor = await crmActor();
    const leadId = formString(formData, "leadId");
    const context = await requestAuditContext();
    const result = await updateLeadStage({
      actor,
      leadId,
      stage: formString(formData, "stage"),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath(`/admin/crm/leads/${leadId}`);
    revalidatePath("/admin/crm");
    return { status: "success", message: "Lead stage updated." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Stage update failed.",
    };
  }
}

export async function addActivityAction(
  _previous: CrmActionState,
  formData: FormData,
): Promise<CrmActionState> {
  try {
    const actor = await crmActor();
    const leadId = formString(formData, "leadId");
    const summary = formString(formData, "summary");
    if (!summary) return { status: "error", message: "Enter an activity summary." };
    const context = await requestAuditContext();
    await addActivity({
      actor,
      leadId,
      type: formString(formData, "type") || "note",
      summary,
      ...context,
    });
    revalidatePath(`/admin/crm/leads/${leadId}`);
    return { status: "success", message: "Activity recorded." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Activity creation failed.",
    };
  }
}

export async function addTaskAction(
  _previous: CrmActionState,
  formData: FormData,
): Promise<CrmActionState> {
  try {
    const actor = await crmActor();
    const leadId = formString(formData, "leadId");
    const title = formString(formData, "title");
    if (!title) return { status: "error", message: "Enter a task title." };
    const due = formString(formData, "dueAt");
    const context = await requestAuditContext();
    await addTask({
      actor,
      leadId,
      title,
      dueAt: due ? new Date(due) : null,
      ...context,
    });
    revalidatePath(`/admin/crm/leads/${leadId}`);
    return { status: "success", message: "Task created." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Task creation failed.",
    };
  }
}
