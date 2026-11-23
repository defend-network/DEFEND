import { and, eq, inArray, isNull } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  roleAssignments,
  session,
  twoFactor,
  user,
} from "@/db/schema";

const adminRoles = ["owner", "national_admin", "chapter_admin", "staff"];

export async function listAdminMfaUsers() {
  const db = await getDb();
  const rows = await db
    .selectDistinct({
      userId: user.id,
      name: user.name,
      email: user.email,
      twoFactorEnabled: user.twoFactorEnabled,
    })
    .from(user)
    .innerJoin(roleAssignments, eq(roleAssignments.userId, user.id))
    .where(
      and(
        inArray(roleAssignments.roleKey, adminRoles),
        isNull(roleAssignments.revokedAt),
      ),
    )
    .limit(100);
  return rows;
}

export async function resetUserMfa(input: {
  actor: ActorContext;
  targetUserId: string;
  reason: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (input.actor.userId === input.targetUserId) {
    return {
      ok: false as const,
      error: "Use a backup code or the normal recovery flow for your own account.",
    };
  }

  const db = await getDb();
  const targetRows = await db
    .select({ id: user.id, email: user.email })
    .from(user)
    .where(eq(user.id, input.targetUserId))
    .limit(1);
  const target = targetRows[0];
  if (!target) return { ok: false as const, error: "User not found." };

  await db.delete(twoFactor).where(eq(twoFactor.userId, input.targetUserId));
  await db
    .update(user)
    .set({ twoFactorEnabled: false, updatedAt: new Date() })
    .where(eq(user.id, input.targetUserId));
  await db.delete(session).where(eq(session.userId, input.targetUserId));

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "admin.mfa.reset",
    targetType: "user",
    targetId: input.targetUserId,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { reason: input.reason.trim().slice(0, 200) },
  });

  return { ok: true as const, email: target.email };
}
