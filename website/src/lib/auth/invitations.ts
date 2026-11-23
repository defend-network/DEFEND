import { and, eq, isNull, gt } from "drizzle-orm";

import { canAcceptLivePayments } from "@/lib/config/features";
import { getAuth } from "@/lib/auth/auth";
import { getDb } from "@/lib/db/client";
import { sendEmail } from "@/lib/email/send";
import { membershipActivatedEmail } from "@/lib/email/templates";
import {
  chapters,
  invitations,
  memberProfiles,
  membershipApplications,
  memberships,
  membershipStatusHistory,
  roleAssignments,
} from "@/db/schema";

export const INVITATION_TTL_MS = 48 * 60 * 60 * 1000;
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 512;

export type InvitationState = "pending" | "expired" | "consumed" | "revoked";

export type InvitationRecordLike = {
  expiresAt: Date;
  consumedAt: Date | null;
  revokedAt: Date | null;
};

export type GeneratedInvitationToken = {
  token: string;
};

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function generateInvitationToken(): GeneratedInvitationToken {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return { token: `inv_${base64Url(bytes)}` };
}

export async function hashInvitationToken(token: string): Promise<string> {
  const data = new TextEncoder().encode(token);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(digest);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

export function invitationState(
  invitation: InvitationRecordLike,
  now = new Date(),
): InvitationState {
  if (invitation.consumedAt) return "consumed";
  if (invitation.revokedAt) return "revoked";
  if (invitation.expiresAt.getTime() <= now.getTime()) return "expired";
  return "pending";
}

export function isAcceptablePassword(password: string): boolean {
  return (
    password.length >= MIN_PASSWORD_LENGTH &&
    password.length <= MAX_PASSWORD_LENGTH
  );
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export async function createInvitation(input: {
  email: string;
  createdBy?: string | null;
  applicationId?: string | null;
  intendedRole?: "member" | "staff" | "chapter_admin" | "national_admin";
  now?: Date;
}): Promise<{ invitationId: string; token: string; expiresAt: Date }> {
  const db = await getDb();
  const { token } = generateInvitationToken();
  const tokenHash = await hashInvitationToken(token);
  const now = input.now ?? new Date();
  const expiresAt = new Date(now.getTime() + INVITATION_TTL_MS);
  const invitationId = `inv_${crypto.randomUUID()}`;

  await db.insert(invitations).values({
    id: invitationId,
    email: normalizeEmail(input.email),
    tokenHash,
    purpose: "member_activation",
    intendedRole: input.intendedRole ?? "member",
    applicationId: input.applicationId ?? null,
    expiresAt,
    createdBy: input.createdBy ?? null,
    deliveryStatus: "not_configured",
    deliveryError: "Email transport is not configured.",
    createdAt: now,
  });

  return { invitationId, token, expiresAt };
}

export async function getInvitationStatus(token: string): Promise<{
  state: InvitationState;
  email?: string;
  expiresAt?: Date;
} | null> {
  if (!token || token.length > 512) return null;
  const db = await getDb();
  const tokenHash = await hashInvitationToken(token);
  const rows = await db
    .select({
      email: invitations.email,
      expiresAt: invitations.expiresAt,
      consumedAt: invitations.consumedAt,
      revokedAt: invitations.revokedAt,
    })
    .from(invitations)
    .where(eq(invitations.tokenHash, tokenHash))
    .limit(1);

  const row = rows[0];
  if (!row) return null;
  return {
    state: invitationState(row),
    email: row.email,
    expiresAt: row.expiresAt,
  };
}

function splitLegalName(value: string): { first: string; last: string } {
  const parts = value.trim().split(/\s+/);
  if (parts.length <= 1) return { first: value.trim(), last: "" };
  return { first: parts.slice(0, -1).join(" "), last: parts.at(-1) ?? "" };
}

function generateMemberNumber(): string {
  const year = new Date().getUTCFullYear();
  const suffix = crypto.randomUUID().replaceAll("-", "").slice(0, 8).toUpperCase();
  return `DEF-${year}-${suffix}`;
}

export async function activateInvitation(input: {
  token: string;
  password: string;
  name: string;
}): Promise<{
  userId: string;
  email: string;
  memberNumber?: string;
  chapterName?: string;
}> {
  if (!input.token || input.token.length > 512) {
    throw new Error("Invitation is unavailable.");
  }
  if (!isAcceptablePassword(input.password)) {
    throw new Error(
      `Password must be between ${MIN_PASSWORD_LENGTH} and ${MAX_PASSWORD_LENGTH} characters.`,
    );
  }

  const db = await getDb();
  const tokenHash = await hashInvitationToken(input.token);
  const rows = await db
    .select()
    .from(invitations)
    .where(eq(invitations.tokenHash, tokenHash))
    .limit(1);
  const invitation = rows[0];

  if (!invitation || invitationState(invitation) !== "pending") {
    throw new Error("Invitation is unavailable.");
  }

  const auth = await getAuth();
  const context = (await auth.$context) as unknown as {
    internalAdapter: {
      createUser: (input: {
        email: string;
        name: string;
        emailVerified: boolean;
      }) => Promise<{ id: string; email: string }>;
      linkAccount: (input: {
        userId: string;
        providerId: string;
        accountId: string;
        password: string;
      }) => Promise<unknown>;
      deleteUser: (userId: string) => Promise<unknown>;
    };
    password: { hash: (password: string) => Promise<string> };
  };

  const created = await context.internalAdapter.createUser({
    email: invitation.email,
    name: input.name.trim(),
    emailVerified: true,
  });

  try {
    const passwordHash = await context.password.hash(input.password);
    await context.internalAdapter.linkAccount({
      userId: created.id,
      providerId: "credential",
      accountId: created.id,
      password: passwordHash,
    });

    let memberNumber: string | undefined;
    let chapterName: string | undefined;

    if (invitation.applicationId) {
      const applicationRows = await db
        .select()
        .from(membershipApplications)
        .where(eq(membershipApplications.id, invitation.applicationId))
        .limit(1);
      const application = applicationRows[0];
      if (!application) {
        throw new Error("The linked application is unavailable.");
      }

      const existingMembership = await db
        .select({ id: memberships.id })
        .from(memberships)
        .where(eq(memberships.applicationId, application.id))
        .limit(1);
      if (existingMembership.length > 0) {
        throw new Error("A membership already exists for this application.");
      }

      const chapterId =
        application.desiredChapterId ??
        application.recommendedChapterId ??
        "chapter_pasco";
      const chapterRows = await db
        .select({ name: chapters.name })
        .from(chapters)
        .where(eq(chapters.id, chapterId))
        .limit(1);
      chapterName = chapterRows[0]?.name ?? "Pasco County";

      const legalName = splitLegalName(application.legalName);
      const now = new Date();
      memberNumber = generateMemberNumber();
      const membershipStatus = canAcceptLivePayments()
        ? "pending_payment"
        : "founding_access";

      await db.insert(memberProfiles).values({
        id: `profile_${crypto.randomUUID()}`,
        userId: created.id,
        legalFirstName: legalName.first,
        legalLastName: legalName.last,
        preferredName: application.preferredName,
        phoneEncrypted: application.phoneEncrypted,
        city: application.city,
        state: application.state,
        postalCode: application.postalCode,
        chapterId,
        joinedAt: now,
        status: "active",
        createdAt: now,
        updatedAt: now,
      });

      const membershipId = `membership_${crypto.randomUUID()}`;
      await db.insert(memberships).values({
        id: membershipId,
        userId: created.id,
        applicationId: application.id,
        chapterId,
        memberNumber,
        status: membershipStatus,
        duesStatus: "not_started",
        joinedAt: now,
        activatedAt: now,
        createdAt: now,
        updatedAt: now,
      });

      await db.insert(membershipStatusHistory).values({
        id: `msh_${crypto.randomUUID()}`,
        membershipId,
        fromStatus: null,
        toStatus: membershipStatus,
        reason: "Account activation",
        actorId: created.id,
        createdAt: now,
      });

      await db.insert(roleAssignments).values({
        id: `role_${crypto.randomUUID()}`,
        userId: created.id,
        roleKey: "member",
        scopeType: "self",
        scopeId: null,
        grantedBy: created.id,
        grantedAt: now,
      });

      await db
        .update(membershipApplications)
        .set({ status: "activated", updatedAt: now })
        .where(eq(membershipApplications.id, application.id));

      await sendEmail(
        membershipActivatedEmail({
          to: created.email,
          name: input.name,
          memberNumber,
          chapterName,
        }),
      );
    }

    const consumed = await db
      .update(invitations)
      .set({ consumedAt: new Date() })
      .where(
        and(
          eq(invitations.id, invitation.id),
          isNull(invitations.consumedAt),
          isNull(invitations.revokedAt),
          gt(invitations.expiresAt, new Date()),
        ),
      )
      .returning({ id: invitations.id });

    if (consumed.length !== 1) {
      throw new Error("Invitation is unavailable.");
    }

    return {
      userId: created.id,
      email: created.email,
      memberNumber,
      chapterName,
    };
  } catch (error) {
    await context.internalAdapter.deleteUser(created.id).catch(() => undefined);
    throw error;
  }
}
