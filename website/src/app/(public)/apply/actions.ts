"use server";

import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { encryptPii } from "@/lib/security/pii";
import {
  applicationSchema,
  validationFieldErrors,
} from "@/lib/validation/application";
import { membershipApplications } from "@/db/schema";
import type { ApplicationFormState } from "./form-state";

function applicationNumber(): string {
  const year = new Date().getUTCFullYear();
  const random = crypto.randomUUID().replace(/-/g, "").slice(0, 8).toUpperCase();
  return `APP-${year}-${random}`;
}

export async function submitApplication(
  _previous: ApplicationFormState,
  formData: FormData,
): Promise<ApplicationFormState> {
  const honeypot = String(formData.get("website") ?? "");
  if (honeypot.trim()) {
    return {
      status: "success",
      message:
        "Thank you. Your application has been received and will be reviewed.",
    };
  }

  const parsed = applicationSchema.safeParse({
    legalName: formData.get("legalName"),
    preferredName: formData.get("preferredName") || undefined,
    email: formData.get("email"),
    phone: formData.get("phone") || undefined,
    city: formData.get("city"),
    state: formData.get("state"),
    postalCode: formData.get("postalCode") || undefined,
    desiredChapterId: formData.get("desiredChapterId"),
    interests: formData.getAll("interests").map(String),
    skills: formData.get("skills") || undefined,
    volunteerInterests: formData.getAll("volunteerInterests").map(String),
    programInterests: formData.getAll("programInterests").map(String),
    policiesAccepted: formData.get("policiesAccepted"),
    privacyAcknowledged: formData.get("privacyAcknowledged"),
  });

  if (!parsed.success) {
    return {
      status: "error",
      message: "Please correct the highlighted fields.",
      fieldErrors: validationFieldErrors(parsed.error),
    };
  }

  const email = parsed.data.email.toLowerCase();
  const number = applicationNumber();

  try {
    const db = await getDb();
    const existing = await db
      .select({ id: membershipApplications.id })
      .from(membershipApplications)
      .where(eq(membershipApplications.email, email))
      .limit(1);

    if (existing.length > 0) {
      return {
        status: "error",
        message:
          "An application with this email address already exists. Contact DEFEND if you need to update it.",
      };
    }

    const phoneEncrypted = parsed.data.phone
      ? await encryptPii(parsed.data.phone)
      : null;

    await db.insert(membershipApplications).values({
      id: `app_${crypto.randomUUID()}`,
      applicationNumber: number,
      legalName: parsed.data.legalName,
      preferredName: parsed.data.preferredName ?? null,
      email,
      phoneEncrypted,
      city: parsed.data.city,
      state: parsed.data.state.toUpperCase(),
      postalCode: parsed.data.postalCode ?? null,
      desiredChapterId: parsed.data.desiredChapterId,
      interestsJson: JSON.stringify(parsed.data.interests),
      skillsJson: JSON.stringify(
        parsed.data.skills ? [parsed.data.skills] : [],
      ),
      volunteerInterestsJson: JSON.stringify(
        parsed.data.volunteerInterests,
      ),
      programInterestsJson: JSON.stringify(parsed.data.programInterests),
      policiesAcceptedAt: new Date(),
      privacyAcknowledgedAt: new Date(),
      status: "submitted",
      submittedAt: new Date(),
      notificationStatus: "not_configured",
    });

    return {
      status: "success",
      message:
        "Your application has been received. An administrator will review it manually.",
      applicationNumber: number,
    };
  } catch (error) {
    console.error(
      "application_submission_failed",
      error instanceof Error ? error.name : "unknown",
    );
    return {
      status: "error",
      message:
        "We could not save your application. Please try again or email DEFEND directly.",
    };
  }
}
