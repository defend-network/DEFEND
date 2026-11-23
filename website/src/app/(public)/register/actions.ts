"use server";

import { eq } from "drizzle-orm";

import { getSignupAuth } from "@/lib/auth/free-signup";
import { recordAuditEvent } from "@/lib/audit/audit";
import { getDb } from "@/lib/db/client";
import { getTierByKey } from "@/lib/membership/tiers";
import { getRequestIp } from "@/lib/security/request-ip";
import { checkRateLimit, rateLimitKey } from "@/lib/security/rate-limit";
import { verifyTurnstile } from "@/lib/security/turnstile";
import {
  memberProfiles,
  memberships,
  membershipStatusHistory,
} from "@/db/schema";
import type { FreeRegistrationState } from "./state";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function splitName(value: string): { first: string; last: string } {
  const parts = value.trim().split(/\s+/);
  if (parts.length <= 1) return { first: value.trim(), last: "" };
  return { first: parts.slice(0, -1).join(" "), last: parts.at(-1) ?? "" };
}

function freeMemberNumber(): string {
  const year = new Date().getUTCFullYear();
  const random = crypto.randomUUID().replace(/-/g, "").slice(0, 8).toUpperCase();
  return `FREE-${year}-${random}`;
}

export async function registerFreeAccount(
  _previous: FreeRegistrationState,
  formData: FormData,
): Promise<FreeRegistrationState> {
  const honeypot = String(formData.get("website") ?? "");
  if (honeypot.trim()) {
    return {
      status: "success",
      message: "Check your email to continue.",
    };
  }

  const name = String(formData.get("name") ?? "").trim();
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  const adultConfirmed = formData.get("adultConfirmed") === "on";

  if (name.length < 2 || name.length > 120) {
    return { status: "error", message: "Enter your full name." };
  }
  if (!EMAIL_PATTERN.test(email) || email.length > 254) {
    return { status: "error", message: "Enter a valid email address." };
  }
  if (password.length < 12 || password.length > 512) {
    return {
      status: "error",
      message: "Use a password of at least 12 characters.",
    };
  }
  if (!adultConfirmed) {
    return {
      status: "error",
      message: "Free registration is currently limited to adults age 18 or older.",
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

  const limiter = await checkRateLimit({
    key: rateLimitKey("free-registration-ip", ip ?? "unknown"),
    limit: 10,
    windowSeconds: 15 * 60,
  });
  if (!limiter.allowed) {
    return {
      status: "error",
      message: "Too many registration attempts. Try again later.",
    };
  }

  try {
    const tier = await getTierByKey("free");
    if (!tier) {
      return {
        status: "error",
        message: "Free membership is not configured yet. Contact DEFEND.",
      };
    }

    const signupAuth = await getSignupAuth();
    const result = (await signupAuth.api.signUpEmail({
      body: { name, email, password },
    })) as {
      token?: string;
      user?: { id: string; name: string; email: string };
    };
    const createdUser = result.user;
    if (!createdUser?.id) {
      return {
        status: "error",
        message:
          "We could not complete registration. If you already have an account, sign in or contact DEFEND.",
      };
    }

    if (result.token) {
      const context = await signupAuth.$context;
      await context.internalAdapter
        .deleteSession(result.token)
        .catch(() => undefined);
    }

    const db = await getDb();
    const existing = await db
      .select({ id: memberships.id })
      .from(memberships)
      .where(eq(memberships.userId, createdUser.id))
      .limit(1);

    if (!existing[0]) {
      const membershipId = `mem_${crypto.randomUUID()}`;
      const { first, last } = splitName(createdUser.name || name);
      const now = new Date();
      await db.insert(memberships).values({
        id: membershipId,
        userId: createdUser.id,
        tierId: tier.id,
        memberNumber: freeMemberNumber(),
        status: "free_access",
        duesStatus: "not_applicable",
        joinedAt: now,
        createdAt: now,
        updatedAt: now,
      });
      await db.insert(memberProfiles).values({
        id: `profile_${crypto.randomUUID()}`,
        userId: createdUser.id,
        legalFirstName: first,
        legalLastName: last,
        status: "free_account",
        joinedAt: now,
        createdAt: now,
        updatedAt: now,
      });
      await db.insert(membershipStatusHistory).values({
        id: `msh_${crypto.randomUUID()}`,
        membershipId,
        fromStatus: null,
        toStatus: "free_access",
        reason: "Free self-service registration",
        actorId: null,
        createdAt: now,
      });
      await recordAuditEvent({
        actorUserId: null,
        action: "membership.free.register",
        targetType: "membership",
        targetId: membershipId,
        outcome: "success",
        metadata: { tier: "free" },
      });
    }

    return {
      status: "success",
      message:
        "Registration received. Check your email to verify your address, then sign in. If email delivery is not configured, use the development outbox.",
    };
  } catch (error) {
    console.error(
      "free_registration_failed",
      error instanceof Error ? error.name : "unknown",
    );
    return {
      status: "error",
      message:
        "We could not complete registration. If you already have an account, sign in or contact DEFEND.",
    };
  }
}
