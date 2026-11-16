"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import { resetUserMfa } from "@/lib/auth/mfa-recovery";
import type { MfaRecoveryState } from "./state";

export async function resetMfaAction(
  _previous: MfaRecoveryState,
  formData: FormData,
): Promise<MfaRecoveryState> {
  try {
    const actor = await getActor();
    if (!actor || !can(actor, "system.users")) {
      throw new Error("MFA-verified owner access is required.");
    }
    const targetUserId = String(formData.get("targetUserId") ?? "");
    const reason = String(formData.get("reason") ?? "");
    const context = await requestAuditContext();
    const result = await resetUserMfa({
      actor,
      targetUserId,
      reason,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/security");
    return {
      status: "success",
      message: `MFA reset for ${result.email}. All sessions were revoked.`,
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "MFA reset failed.",
    };
  }
}
