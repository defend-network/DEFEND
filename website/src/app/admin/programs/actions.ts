"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import { createProgram } from "@/lib/programs/programs";
import type { ProgramActionState } from "./action-state";

export async function createProgramAction(
  _previous: ProgramActionState,
  formData: FormData,
): Promise<ProgramActionState> {
  try {
    const actor = await getActor();
    if (!actor || !can(actor, "events.manage")) {
      throw new Error("MFA-verified program-management access is required.");
    }
    const title = String(formData.get("title") ?? "").trim();
    if (!title) return { status: "error", message: "Enter a program title." };
    const capacity = Number(formData.get("capacity") ?? "");
    const fee = Number(formData.get("feeDollars") ?? "");
    const context = await requestAuditContext();
    const result = await createProgram({
      actor,
      title,
      summary: String(formData.get("summary") ?? ""),
      description: String(formData.get("description") ?? ""),
      status: String(formData.get("status") ?? "planned"),
      capacity: Number.isFinite(capacity) && capacity > 0 ? capacity : null,
      feeCents: Number.isFinite(fee) && fee > 0 ? Math.round(fee * 100) : 0,
      eligibility: String(formData.get("eligibility") ?? ""),
      familyFriendly: formData.get("familyFriendly") === "on",
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/programs");
    return { status: "success", message: "Program created." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Program creation failed." };
  }
}
