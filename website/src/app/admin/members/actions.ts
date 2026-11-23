"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import {
  assignMemberChapter,
  updateMembershipStatus,
} from "@/lib/membership/members";
import type { MemberActionState } from "./action-state";

async function memberActor() {
  const actor = await getActor();
  if (!actor) throw new Error("Sign in to continue.");
  return actor;
}

export async function updateMemberStatusAction(
  _previous: MemberActionState,
  formData: FormData,
): Promise<MemberActionState> {
  try {
    const actor = await memberActor();
    const userId = String(formData.get("userId") ?? "");
    const status = String(formData.get("status") ?? "");
    const reason = String(formData.get("reason") ?? "");
    const context = await requestAuditContext();
    const result = await updateMembershipStatus({
      userId,
      status,
      reason,
      actor,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/members");
    revalidatePath(`/admin/members/${userId}`);
    return { status: "success", message: "Membership status updated." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Status update failed.",
    };
  }
}

export async function assignChapterAction(
  _previous: MemberActionState,
  formData: FormData,
): Promise<MemberActionState> {
  try {
    const actor = await memberActor();
    const userId = String(formData.get("userId") ?? "");
    const chapterId = String(formData.get("chapterId") ?? "");
    const context = await requestAuditContext();
    const result = await assignMemberChapter({
      userId,
      chapterId,
      actor,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/members");
    revalidatePath(`/admin/members/${userId}`);
    return { status: "success", message: "Chapter assignment updated." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Chapter assignment failed.",
    };
  }
}
