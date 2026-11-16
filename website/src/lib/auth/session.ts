import { and, eq, isNull } from "drizzle-orm";
import { headers } from "next/headers";

import { getAuth } from "@/lib/auth/auth";
import { getDb } from "@/lib/db/client";
import { roleAssignments } from "@/db/schema";
import {
  type ActorContext,
  type Permission,
  type ResourceScope,
  type RoleAssignment,
  isRoleKey,
  assertCan,
  actorRequiresMfa,
} from "@/lib/policy/permissions";

export async function getSession() {
  const auth = await getAuth();
  return auth.api.getSession({ headers: await headers() });
}

export async function getActor(): Promise<ActorContext | null> {
  const session = await getSession();
  if (!session?.user) return null;

  const db = await getDb();
  const rows = await db
    .select({
      roleKey: roleAssignments.roleKey,
      scopeType: roleAssignments.scopeType,
      scopeId: roleAssignments.scopeId,
    })
    .from(roleAssignments)
    .where(
      and(
        eq(roleAssignments.userId, session.user.id),
        isNull(roleAssignments.revokedAt),
      ),
    );

  const roles: RoleAssignment[] = rows
    .filter((row) => isRoleKey(row.roleKey))
    .map((row) => ({
      roleKey: row.roleKey as RoleAssignment["roleKey"],
      scopeType:
        row.scopeType === "global" || row.scopeType === "chapter"
          ? row.scopeType
          : "self",
      scopeId: row.scopeId,
    }));

  if (roles.length === 0) {
    roles.push({ roleKey: "member", scopeType: "self", scopeId: null });
  }

  const actor: ActorContext = {
    userId: session.user.id,
    displayName: session.user.name,
    email: session.user.email,
    roles,
    // A session only exists after the Better Auth 2FA challenge when the user
    // has TOTP enabled. Administrators without MFA fail closed.
    mfaVerified: Boolean(
      (session.user as { twoFactorEnabled?: boolean }).twoFactorEnabled,
    ),
  };

  return actor;
}

export async function requireActor(): Promise<ActorContext> {
  const actor = await getActor();
  if (!actor) {
    throw new Error("Sign in to continue.");
  }
  return actor;
}

export async function requirePermission(
  permission: Permission,
  resource?: ResourceScope,
): Promise<ActorContext> {
  const actor = await getActor();
  assertCan(actor, permission, resource);
  return actor;
}

export function actorNeedsMfa(actor: ActorContext): boolean {
  return actorRequiresMfa(actor);
}
