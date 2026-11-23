"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { registerForEvent } from "@/lib/events/events";
import type { EventRegistrationState } from "./registration-state";

export async function registerEventAction(
  _previous: EventRegistrationState,
  formData: FormData,
): Promise<EventRegistrationState> {
  try {
    const actor = await getActor();
    if (!actor) {
      return { status: "error", message: "Sign in to register for an event." };
    }
    const eventId = String(formData.get("eventId") ?? "");
    const context = await requestAuditContext();
    const result = await registerForEvent({
      userId: actor.userId,
      eventId,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/events");
    return {
      status: "success",
      message:
        result.status === "waitlisted"
          ? "The event is at capacity. You are on the waitlist."
          : result.alreadyRegistered
            ? "You are already registered for this event."
            : "Your event registration is confirmed.",
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Registration failed.",
    };
  }
}
