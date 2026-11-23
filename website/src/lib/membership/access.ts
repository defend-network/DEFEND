import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { membershipTiers, memberships } from "@/db/schema";

export const PAID_MEMBERSHIP_STATUSES = new Set([
  "founding_access",
  "pending_payment",
  "active",
  "grace",
]);

export function isPaidMembershipStatus(status: string | null | undefined): boolean {
  return Boolean(status && PAID_MEMBERSHIP_STATUSES.has(status));
}

export function isFreeMembershipStatus(status: string | null | undefined): boolean {
  return status === "free_access";
}

export function canRegisterForEvent(input: {
  membershipStatus: string | null | undefined;
  feeCents: number | null | undefined;
}): boolean {
  if (!input.membershipStatus) return false;
  if (PAID_MEMBERSHIP_STATUSES.has(input.membershipStatus)) return true;
  return (
    input.membershipStatus === "free_access" && (input.feeCents ?? 0) === 0
  );
}

export async function getMemberStanding(userId: string) {
  const db = await getDb();
  const rows = await db
    .select({
      membershipId: memberships.id,
      status: memberships.status,
      duesStatus: memberships.duesStatus,
      tierKey: membershipTiers.key,
      tierName: membershipTiers.name,
      chapterId: memberships.chapterId,
    })
    .from(memberships)
    .leftJoin(membershipTiers, eq(memberships.tierId, membershipTiers.id))
    .where(eq(memberships.userId, userId))
    .limit(1);
  return rows[0] ?? null;
}
