import { NextResponse } from "next/server";
import { eq } from "drizzle-orm";

import { getActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { createCardToken } from "@/lib/membership/card";
import { chapters, memberships } from "@/db/schema";

export const dynamic = "force-dynamic";

const allowedStatuses = new Set([
  "founding_access",
  "pending_payment",
  "active",
  "grace",
]);

export async function GET() {
  const actor = await getActor();
  if (!actor) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const db = await getDb();
  const rows = await db
    .select({
      id: memberships.id,
      memberNumber: memberships.memberNumber,
      status: memberships.status,
      duesStatus: memberships.duesStatus,
      chapterName: chapters.name,
    })
    .from(memberships)
    .leftJoin(chapters, eq(memberships.chapterId, chapters.id))
    .where(eq(memberships.userId, actor.userId))
    .limit(1);

  const membership = rows[0];
  if (!membership) {
    return NextResponse.json(
      { error: "No membership record is available." },
      { status: 404 },
    );
  }
  if (!allowedStatuses.has(membership.status)) {
    return NextResponse.json(
      { error: "Membership is not currently eligible for a card." },
      { status: 403 },
    );
  }

  const { token, expiresAt } = await createCardToken({
    membershipId: membership.id,
    userId: actor.userId,
    ttlSeconds: 300,
  });

  return NextResponse.json({
    token,
    expiresAt: expiresAt.toISOString(),
    memberNumber: membership.memberNumber,
    displayName: actor.displayName,
    chapterName: membership.chapterName ?? "Pasco County",
    status: membership.status,
    duesStatus: membership.duesStatus,
  });
}
