import { and, desc, eq, isNull } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { ROLE_KEYS, type ActorContext, type RoleKey } from "@/lib/policy/permissions";
import { roleAssignments, user } from "@/db/schema";

export async function listUsersAndRoles() {
  const db = await getDb();
  const [users, assignments] = await Promise.all([
    db
      .select({ id: user.id, name: user.name, email: user.email, twoFactorEnabled: user.twoFactorEnabled })
      .from(user)
      .orderBy(desc(user.createdAt))
      .limit(200),
    db
      .select()
      .from(roleAssignments)
      .where(isNull(roleAssignments.revokedAt))
      .orderBy(desc(roleAssignments.grantedAt))
      .limit(200),
  ]);
  return { users, assignments };
}

export async function assignRole(input: {
  actor: ActorContext;
  userId: string;
  roleKey: string;
  scopeType: string;
  scopeId?: string | null;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (!(ROLE_KEYS as readonly string[]).includes(input.roleKey)) {
    return { ok: false as const, error: "Unsupported role." };
  }
  if (input.roleKey === "owner") {
    return { ok: false as const, error: "Owner role is bootstrap-only." };
  }
  const scopeType = input.scopeType === "chapter" ? "chapter" : "global";
  if (scopeType === "chapter" && !input.scopeId) {
    return { ok: false as const, error: "Choose a chapter for a chapter-scoped role." };
  }
  const db = await getDb();
  const existing = await db
    .select({ id: roleAssignments.id })
    .from(roleAssignments)
    .where(
      and(
        eq(roleAssignments.userId, input.userId),
        eq(roleAssignments.roleKey, input.roleKey as RoleKey),
        eq(roleAssignments.scopeType, scopeType),
        isNull(roleAssignments.revokedAt),
      ),
    )
    .limit(1);
  if (existing[0]) {
    return { ok: false as const, error: "That role assignment already exists." };
  }
  const id = `role_${crypto.randomUUID()}`;
  await db.insert(roleAssignments).values({
    id,
    userId: input.userId,
    roleKey: input.roleKey,
    scopeType,
    scopeId: scopeType === "chapter" ? input.scopeId ?? null : null,
    grantedBy: input.actor.userId,
    grantedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "system.role.assign",
    targetType: "user",
    targetId: input.userId,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { roleKey: input.roleKey, scopeType, scopeId: input.scopeId ?? null },
  });
  return { ok: true as const, id };
}

export async function revokeRole(input: {
  actor: ActorContext;
  assignmentId: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(roleAssignments)
    .where(eq(roleAssignments.id, input.assignmentId))
    .limit(1);
  const assignment = rows[0];
  if (!assignment) return { ok: false as const, error: "Role assignment not found." };
  if (assignment.roleKey === "owner") {
    return { ok: false as const, error: "Owner role cannot be revoked here." };
  }
  await db
    .update(roleAssignments)
    .set({ revokedAt: new Date(), revokedBy: input.actor.userId })
    .where(eq(roleAssignments.id, assignment.id));
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "system.role.revoke",
    targetType: "user",
    targetId: assignment.userId,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { roleKey: assignment.roleKey, scopeType: assignment.scopeType },
  });
  return { ok: true as const };
}
