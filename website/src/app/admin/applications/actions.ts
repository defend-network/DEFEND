"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import {
  approveApplication,
  denyApplication,
  requestApplicationInfo,
} from "@/lib/membership/applications";
import type { ApplicationActionState } from "./action-state";

async function reviewActor() {
  const actor = await getActor();
  if (!actor) throw new Error("Sign in to continue.");
  return actor;
}

export async function approveApplicationAction(
  _previous: ApplicationActionState,
  formData: FormData,
): Promise<ApplicationActionState> {
  try {
    const actor = await reviewActor();
    const applicationId = String(formData.get("applicationId") ?? "");
    const notes = String(formData.get("notes") ?? "");
    const context = await requestAuditContext();
    const result = await approveApplication({
      applicationId,
      actor,
      notes,
      ...context,
    });
    if (!result.ok) {
      return { status: "error", message: result.error };
    }
    revalidatePath("/admin/applications");
    revalidatePath(`/admin/applications/${applicationId}`);
    return {
      status: "success",
      message:
        result.emailStatus === "outbox"
          ? "Application approved. Invitation saved to the development email outbox."
          : result.emailStatus === "sent"
            ? "Application approved and invitation email sent."
            : "Application approved. Email delivery is not configured; copy the activation link below.",
      activationUrl: result.activationUrl,
      emailStatus: result.emailStatus,
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Approval failed.",
    };
  }
}

export async function denyApplicationAction(
  _previous: ApplicationActionState,
  formData: FormData,
): Promise<ApplicationActionState> {
  try {
    const actor = await reviewActor();
    const applicationId = String(formData.get("applicationId") ?? "");
    const notes = String(formData.get("notes") ?? "");
    const context = await requestAuditContext();
    const result = await denyApplication({
      applicationId,
      actor,
      notes,
      ...context,
    });
    if (!result.ok) {
      return { status: "error", message: result.error };
    }
    revalidatePath("/admin/applications");
    revalidatePath(`/admin/applications/${applicationId}`);
    return {
      status: "success",
      message:
        result.emailStatus === "outbox"
          ? "Application denied. Decision email saved to the development email outbox."
          : "Application denied.",
      emailStatus: result.emailStatus,
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Decision failed.",
    };
  }
}

export async function requestInfoAction(
  _previous: ApplicationActionState,
  formData: FormData,
): Promise<ApplicationActionState> {
  try {
    const actor = await reviewActor();
    const applicationId = String(formData.get("applicationId") ?? "");
    const message = String(formData.get("message") ?? "");
    const context = await requestAuditContext();
    const result = await requestApplicationInfo({
      applicationId,
      actor,
      message,
      ...context,
    });
    if (!result.ok) {
      return { status: "error", message: result.error };
    }
    revalidatePath("/admin/applications");
    revalidatePath(`/admin/applications/${applicationId}`);
    return {
      status: "success",
      message:
        result.emailStatus === "outbox"
          ? "Information request saved and email placed in the development outbox."
          : "Information request recorded. Copy the secure update link below.",
      updateUrl: result.updateUrl,
      emailStatus: result.emailStatus,
    };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error ? error.message : "Information request failed.",
    };
  }
}
