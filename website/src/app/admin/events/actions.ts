"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import {
  createEvent,
  createVolunteerOpportunity,
} from "@/lib/events/events";
import type { EventActionState } from "./action-state";

export async function createEventAction(
  _previous: EventActionState,
  formData: FormData,
): Promise<EventActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");
    const title = String(formData.get("title") ?? "").trim();
    const startsAtRaw = String(formData.get("startsAt") ?? "");
    const startsAt = new Date(startsAtRaw);
    if (!title || Number.isNaN(startsAt.getTime())) {
      return { status: "error", message: "Enter a title and a valid start time." };
    }
    const capacity = Number(formData.get("capacity") ?? "");
    const fee = Number(formData.get("feeDollars") ?? "");
    const context = await requestAuditContext();
    const result = await createEvent({
      actor,
      title,
      summary: String(formData.get("summary") ?? ""),
      description: String(formData.get("description") ?? ""),
      startsAt,
      locationName: String(formData.get("locationName") ?? ""),
      address: String(formData.get("address") ?? ""),
      capacity: Number.isFinite(capacity) && capacity > 0 ? capacity : null,
      feeCents: Number.isFinite(fee) && fee > 0 ? Math.round(fee * 100) : 0,
      familyFriendly: formData.get("familyFriendly") === "on",
      status: formData.get("status") === "published" ? "published" : "draft",
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/events");
    revalidatePath("/events");
    return { status: "success", message: "Event created." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Event creation failed.",
    };
  }
}

export async function createVolunteerAction(
  _previous: EventActionState,
  formData: FormData,
): Promise<EventActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");
    const title = String(formData.get("title") ?? "").trim();
    if (!title) return { status: "error", message: "Enter a title." };
    const slots = Number(formData.get("slots") ?? "");
    const context = await requestAuditContext();
    await createVolunteerOpportunity({
      actor,
      title,
      description: String(formData.get("description") ?? ""),
      slots: Number.isFinite(slots) && slots > 0 ? slots : null,
      skills: String(formData.get("skills") ?? ""),
      availability: String(formData.get("availability") ?? ""),
      isInstructorRole: formData.get("isInstructorRole") === "on",
      ...context,
    });
    revalidatePath("/admin/events");
    revalidatePath("/members/volunteers");
    return { status: "success", message: "Volunteer opportunity created." };
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error ? error.message : "Volunteer creation failed.",
    };
  }
}
