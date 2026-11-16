import { and, eq, isNull, gt } from "drizzle-orm";

import { getAuth } from "@/lib/auth/auth";
import { getDb } from "@/lib/db/client";
import { invitations } from "@/db/schema";

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

export async function activateInvitation(input: {
  token: string;
  password: string;
  name: string;
}): Promise<{ userId: string; email: string }> {
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

    return { userId: created.id, email: created.email };
  } catch (error) {
    await context.internalAdapter.deleteUser(created.id).catch(() => undefined);
    throw error;
  }
}
