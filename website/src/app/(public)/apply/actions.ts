"use server";

import { and, eq, inArray } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { encryptPii } from "@/lib/security/pii";
import { getRequestIp } from "@/lib/security/request-ip";
import { checkRateLimit, rateLimitKey } from "@/lib/security/rate-limit";
import { verifyTurnstile } from "@/lib/security/turnstile";
import { sendEmail } from "@/lib/email/send";
import { applicationReceivedEmail } from "@/lib/email/templates";
import { recommendChapter } from "@/lib/chapters/recommend";
import { chapters as chapterContent } from "@/lib/content/chapters";
import {
  applicationSchema,
  validationFieldErrors,
} from "@/lib/validation/application";
import { chapters as chapterTable, membershipApplications } from "@/db/schema";
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
    requestedTier: formData.get("requestedTier") ?? "standard",
    interests: formData.getAll("interests").map(String),
    skills: formData.get("skills") || undefined,
    volunteerInterests: formData.getAll("volunteerInterests").map(String),
    programInterests: formData.getAll("programInterests").map(String),
    policiesAccepted: formData.get("policiesAccepted"),
    privacyAcknowledged: formData.get("privacyAcknowledged"),
    adultConfirmed: formData.get("adultConfirmed"),
  });

  if (!parsed.success) {
    return {
      status: "error",
      message: "Please correct the highlighted fields.",
      fieldErrors: validationFieldErrors(parsed.error),
    };
  }

  const ip = await getRequestIp();
  const turnstile = await verifyTurnstile(
    String(formData.get("cf-turnstile-response") ?? ""),
    ip,
  );
  if (!turnstile.ok) {
    return {
      status: "error",
      message:
        turnstile.error ??
        "Spam protection could not verify this request. Please try again.",
    };
  }

  const email = parsed.data.email.toLowerCase();
  const limiter = await checkRateLimit({
    key: rateLimitKey("application", `${ip ?? "unknown"}:${email}`),
    limit: 5,
    windowSeconds: 15 * 60,
  });
  if (!limiter.allowed) {
    return {
      status: "error",
      message: "Too many application attempts. Try again later.",
    };
  }

  const number = applicationNumber();

  try {
    const db = await getDb();
    const chapterRows = await db
      .select({ id: chapterTable.id })
      .from(chapterTable)
      .where(
        and(
          eq(chapterTable.id, parsed.data.desiredChapterId),
          inArray(chapterTable.status, ["operating", "in_development"]),
        ),
      )
      .limit(1);
    if (!chapterRows[0]) {
      return {
        status: "error",
        message: "Select a chapter that is accepting applications.",
        fieldErrors: {
          desiredChapterId: "Select a chapter that is accepting applications.",
        },
      };
    }

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
    const recommendation = recommendChapter({
      state: parsed.data.state,
      postalCode: parsed.data.postalCode,
      operatingChapters: chapterContent,
    });

    const applicationId = `app_${crypto.randomUUID()}`;
    await db.insert(membershipApplications).values({
      id: applicationId,
      applicationNumber: number,
      legalName: parsed.data.legalName,
      preferredName: parsed.data.preferredName ?? null,
      email,
      phoneEncrypted,
      city: parsed.data.city,
      state: parsed.data.state.toUpperCase(),
      postalCode: parsed.data.postalCode ?? null,
      desiredChapterId: parsed.data.desiredChapterId,
      requestedTierKey: parsed.data.requestedTier,
      recommendedChapterId: recommendation.chapterId,
      referralSource: String(formData.get("referralSource") ?? "").slice(0, 200) || null,
      referrerUrl: String(formData.get("referrerUrl") ?? "").slice(0, 500) || null,
      utmSource: String(formData.get("utmSource") ?? "").slice(0, 120) || null,
      utmMedium: String(formData.get("utmMedium") ?? "").slice(0, 120) || null,
      utmCampaign: String(formData.get("utmCampaign") ?? "").slice(0, 120) || null,
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
      adultConfirmedAt: new Date(),
      status: "submitted",
      submittedAt: new Date(),
      notificationStatus: "not_configured",
    });

    const emailResult = await sendEmail(
      applicationReceivedEmail({
        to: email,
        name: parsed.data.preferredName || parsed.data.legalName,
        applicationNumber: number,
      }),
    );
    await db
      .update(membershipApplications)
      .set({ notificationStatus: emailResult.status, updatedAt: new Date() })
      .where(eq(membershipApplications.id, applicationId));

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
