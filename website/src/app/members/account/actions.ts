"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import {
  updateMemberAccount,
  type DirectoryPreferences,
  type NotificationPreferences,
} from "@/lib/membership/profile";
import type { AccountActionState } from "./action-state";

function flag(formData: FormData, name: string): boolean {
  return formData.get(name) === "on";
}

export async function updateAccountAction(
  _previous: AccountActionState,
  formData: FormData,
): Promise<AccountActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");

    const directoryPreferences: DirectoryPreferences = {
      showChapter: flag(formData, "showChapter"),
      showProfession: flag(formData, "showProfession"),
      showBusiness: flag(formData, "showBusiness"),
      showSkills: flag(formData, "showSkills"),
      showEmail: flag(formData, "showEmail"),
      showPhone: flag(formData, "showPhone"),
      showVolunteerInterests: flag(formData, "showVolunteerInterests"),
    };
    const notificationPreferences: NotificationPreferences = {
      membership: flag(formData, "notifyMembership"),
      events: flag(formData, "notifyEvents"),
      newsletter: flag(formData, "notifyNewsletter"),
    };

    const context = await requestAuditContext();
    const result = await updateMemberAccount({
      userId: actor.userId,
      actor,
      preferredName: String(formData.get("preferredName") ?? ""),
      phone: String(formData.get("phone") ?? ""),
      city: String(formData.get("city") ?? ""),
      state: String(formData.get("state") ?? ""),
      postalCode: String(formData.get("postalCode") ?? ""),
      directoryVisible: flag(formData, "directoryVisible"),
      familyParticipation: flag(formData, "familyParticipation"),
      profession: String(formData.get("profession") ?? ""),
      businessName: String(formData.get("businessName") ?? ""),
      skills: String(formData.get("skills") ?? ""),
      volunteerInterests: formData.getAll("volunteerInterests").map(String),
      directoryPreferences,
      notificationPreferences,
      ...context,
    });

    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/members/account");
    revalidatePath("/members");
    return { status: "success", message: "Profile and preferences updated." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Profile update failed.",
    };
  }
}

