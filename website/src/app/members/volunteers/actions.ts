"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { registerForVolunteer } from "@/lib/events/events";
import type { VolunteerRegistrationState } from "./state";

export async function registerVolunteerAction(
  _previous: VolunteerRegistrationState,
  formData: FormData,
): Promise<VolunteerRegistrationState> {
  try {
    const actor = await getActor();
    if (!actor) return { status: "error", message: "Sign in to continue." };
    const opportunityId = String(formData.get("opportunityId") ?? "");
    const context = await requestAuditContext();
    const result = await registerForVolunteer({
      userId: actor.userId,
      opportunityId,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/members/volunteers");
    return {
      status: "success",
      message: result.alreadyRegistered
        ? "You are already registered for this opportunity."
        : "Volunteer registration recorded.",
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Registration failed.",
    };
  }
}
