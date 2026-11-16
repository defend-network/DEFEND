import {
  and,
  count,
  desc,
  eq,
  like,
  or,
  type SQL,
} from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { decryptPii } from "@/lib/security/pii";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  chapters,
  memberProfiles,
  memberships,
  membershipStatusHistory,
  roleAssignments,
  user,
} from "@/db/schema";

export type MemberListFilter = {
  query?: string;
  status?: string;
  chapterId?: string;
  limit?: number;
  offset?: number;
};

export async function listMembers(filter: MemberListFilter = {}) {
  const db = await getDb();
  const limit = Math.min(Math.max(filter.limit ?? 25, 1), 100);
  const offset = Math.max(filter.offset ?? 0, 0);
  const conditions: SQL[] = [];

  const query = filter.query?.trim();
  if (query) {
    const pattern = `%${query.slice(0, 120)}%`;
    conditions.push(
      or(
        like(user.name, pattern),
        like(user.email, pattern),
        like(memberships.memberNumber, pattern),
      ) as SQL,
    );
  }
  if (filter.status && filter.status !== "all") {
    conditions.push(eq(memberships.status, filter.status));
  }
  if (filter.chapterId && filter.chapterId !== "all") {
    conditions.push(eq(memberships.chapterId, filter.chapterId));
  }

  const where = conditions.length ? and(...conditions) : undefined;

  const [items, totalRows] = await Promise.all([
    db
      .select({
        userId: user.id,
        name: user.name,
        email: user.email,
        memberNumber: memberships.memberNumber,
        membershipStatus: memberships.status,
        duesStatus: memberships.duesStatus,
        chapterId: memberships.chapterId,
        chapterName: chapters.name,
        joinedAt: memberships.joinedAt,
        preferredName: memberProfiles.preferredName,
      })
      .from(memberships)
      .innerJoin(user, eq(memberships.userId, user.id))
      .leftJoin(memberProfiles, eq(memberProfiles.userId, user.id))
      .leftJoin(chapters, eq(memberships.chapterId, chapters.id))
      .where(where)
      .orderBy(desc(memberships.createdAt))
      .limit(limit)
      .offset(offset),
    db
      .select({ value: count() })
      .from(memberships)
      .innerJoin(user, eq(memberships.userId, user.id))
      .where(where),
  ]);

  return {
    items,
    total: totalRows[0]?.value ?? 0,
    limit,
    offset,
  };
}

export async function getMemberDetail(userId: string) {
  const db = await getDb();
  const rows = await db
    .select({
      user: {
        id: user.id,
        name: user.name,
        email: user.email,
        emailVerified: user.emailVerified,
        twoFactorEnabled: user.twoFactorEnabled,
        createdAt: user.createdAt,
      },
      profile: memberProfiles,
      membership: memberships,
      chapterName: chapters.name,
    })
    .from(memberships)
    .innerJoin(user, eq(memberships.userId, user.id))
    .leftJoin(memberProfiles, eq(memberProfiles.userId, user.id))
    .leftJoin(chapters, eq(memberships.chapterId, chapters.id))
    .where(eq(memberships.userId, userId))
    .limit(1);

  const row = rows[0];
  if (!row) return null;

  const phone = row.profile?.phoneEncrypted
    ? await decryptPii(row.profile.phoneEncrypted).catch(() => null)
    : null;

  const [history, assignments, chapterRows] = await Promise.all([
    db
      .select()
      .from(membershipStatusHistory)
      .where(eq(membershipStatusHistory.membershipId, row.membership.id))
      .orderBy(desc(membershipStatusHistory.createdAt))
      .limit(25),
    db
      .select()
      .from(roleAssignments)
      .where(eq(roleAssignments.userId, userId))
      .limit(25),
    db
      .select({ id: chapters.id, name: chapters.name, status: chapters.status })
      .from(chapters),
  ]);

  return {
    ...row,
    phone,
    history,
    roleAssignments: assignments,
    chapters: chapterRows,
  };
}

const allowedStatuses = new Set([
  "founding_access",
  "pending_payment",
  "active",
  "grace",
  "lapsed",
  "cancelled",
  "suspended",
]);

export async function updateMembershipStatus(input: {
  userId: string;
  status: string;
  reason: string;
  actor: ActorContext;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (!allowedStatuses.has(input.status)) {
    return { ok: false, error: "Unsupported membership status." };
  }
  if (input.status === "active" && !input.actor.roles.some(
    (role) => role.roleKey === "owner" || role.roleKey === "national_admin",
  )) {
    return { ok: false, error: "Only an owner or national administrator can mark dues active." };
  }

  const db = await getDb();
  const rows = await db
    .select()
    .from(memberships)
    .where(eq(memberships.userId, input.userId))
    .limit(1);
  const membership = rows[0];
  if (!membership) return { ok: false, error: "Membership not found." };

  await db
    .update(memberships)
    .set({ status: input.status, updatedAt: new Date() })
    .where(eq(memberships.id, membership.id));

  await db.insert(membershipStatusHistory).values({
    id: `msh_${crypto.randomUUID()}`,
    membershipId: membership.id,
    fromStatus: membership.status,
    toStatus: input.status,
    reason: input.reason.trim() || "Administrative status update",
    actorId: input.actor.userId,
    createdAt: new Date(),
  });

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "member.status.update",
    targetType: "membership",
    targetId: membership.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {
      fromStatus: membership.status,
      toStatus: input.status,
      reason: input.reason.trim().slice(0, 200),
    },
  });

  return { ok: true };
}

export async function assignMemberChapter(input: {
  userId: string;
  chapterId: string;
  actor: ActorContext;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const chapterRows = await db
    .select({ id: chapters.id, name: chapters.name })
    .from(chapters)
    .where(eq(chapters.id, input.chapterId))
    .limit(1);
  if (!chapterRows[0]) return { ok: false, error: "Chapter not found." };

  const rows = await db
    .select()
    .from(memberships)
    .where(eq(memberships.userId, input.userId))
    .limit(1);
  const membership = rows[0];
  if (!membership) return { ok: false, error: "Membership not found." };

  await db
    .update(memberships)
    .set({ chapterId: input.chapterId, updatedAt: new Date() })
    .where(eq(memberships.id, membership.id));
  await db
    .update(memberProfiles)
    .set({ chapterId: input.chapterId, updatedAt: new Date() })
    .where(eq(memberProfiles.userId, input.userId));

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "member.chapter.assign",
    targetType: "membership",
    targetId: membership.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {
      fromChapterId: membership.chapterId,
      toChapterId: input.chapterId,
    },
  });

  return { ok: true };
}
