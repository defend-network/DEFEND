"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import { assignRole, revokeRole } from "@/lib/auth/roles";
import type { SystemActionState } from "./action-state";

async function systemActor() {
  const actor = await getActor();
  if (!actor || !can(actor, "system.users")) {
    throw new Error("MFA-verified owner access is required.");
  }
  return actor;
}

export async function assignRoleAction(
  _previous: SystemActionState,
  formData: FormData,
): Promise<SystemActionState> {
  try {
    const actor = await systemActor();
    const context = await requestAuditContext();
    const result = await assignRole({
      actor,
      userId: String(formData.get("userId") ?? ""),
      roleKey: String(formData.get("roleKey") ?? ""),
      scopeType: String(formData.get("scopeType") ?? "global"),
      scopeId: String(formData.get("scopeId") ?? "") || null,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/system");
    return { status: "success", message: "Role assigned." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Role assignment failed." };
  }
}

export async function revokeRoleAction(
  _previous: SystemActionState,
  formData: FormData,
): Promise<SystemActionState> {
  try {
    const actor = await systemActor();
    const context = await requestAuditContext();
    const result = await revokeRole({
      actor,
      assignmentId: String(formData.get("assignmentId") ?? ""),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/system");
    return { status: "success", message: "Role revoked." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Role revocation failed." };
  }
}
