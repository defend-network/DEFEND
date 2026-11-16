"use server";

import { z } from "zod";
import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { getRequestIp } from "@/lib/security/request-ip";
import { checkRateLimit, rateLimitKey } from "@/lib/security/rate-limit";
import { verifyTurnstile } from "@/lib/security/turnstile";
import { newsletterSubscribers } from "@/db/schema";
import type { NewsletterState } from "./state";

const schema = z.object({
  email: z.string().trim().email("Enter a valid email address.").max(320),
  consent: z.string().refine((value) => value === "on", "Consent is required."),
});

export async function subscribeNewsletter(
  _previous: NewsletterState,
  formData: FormData,
): Promise<NewsletterState> {
  const honeypot = String(formData.get("website") ?? "");
  if (honeypot.trim()) {
    return { status: "success", message: "Thank you for subscribing." };
  }
  const parsed = schema.safeParse({
    email: formData.get("email"),
    consent: formData.get("consent"),
  });
  if (!parsed.success) {
    return {
      status: "error",
      message: parsed.error.issues[0]?.message || "Enter a valid email address and consent.",
    };
  }
  const email = parsed.data.email.toLowerCase();
  const ip = await getRequestIp();
  const turnstile = await verifyTurnstile(
    String(formData.get("cf-turnstile-response") ?? ""),
    ip,
  );
  if (!turnstile.ok) {
    return { status: "error", message: turnstile.error || "Spam check failed." };
  }
  const limiter = await checkRateLimit({
    key: rateLimitKey("newsletter", ip ?? email),
    limit: 5,
    windowSeconds: 15 * 60,
  });
  if (!limiter.allowed) {
    return { status: "error", message: "Too many attempts. Try again later." };
  }

  try {
    const db = await getDb();
    const existing = await db
      .select({ id: newsletterSubscribers.id })
      .from(newsletterSubscribers)
      .where(eq(newsletterSubscribers.email, email))
      .limit(1);
    if (existing[0]) {
      await db
        .update(newsletterSubscribers)
        .set({ status: "subscribed", consentAt: new Date(), unsubscribedAt: null })
        .where(eq(newsletterSubscribers.email, email));
    } else {
      await db.insert(newsletterSubscribers).values({
        id: `news_${crypto.randomUUID()}`,
        email,
        status: "subscribed",
        source: "website",
        consentAt: new Date(),
        createdAt: new Date(),
      });
    }
    return {
      status: "success",
      message:
        "You are subscribed to DEFEND updates. No bulk email has been sent; consent is recorded for future approved communications.",
    };
  } catch {
    return { status: "error", message: "Unable to subscribe. Please try again." };
  }
}
