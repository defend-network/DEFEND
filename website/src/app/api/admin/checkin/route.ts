import { NextResponse } from "next/server";
import { and, eq } from "drizzle-orm";
import { z } from "zod";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { recordAuditEvent } from "@/lib/audit/audit";
import { getDb } from "@/lib/db/client";
import { verifyCardToken } from "@/lib/membership/card";
import { can, canAccessModule } from "@/lib/policy/permissions";
import {
  chapters,
  eventCheckins,
  eventRegistrations,
  events,
  memberships,
  user,
} from "@/db/schema";

export const dynamic = "force-dynamic";

const bodySchema = z.object({
  token: z.string().min(1).max(2048),
  eventId: z.string().max(100).optional(),
});

const allowedStatuses = new Set(["founding_access", "pending_payment", "active", "grace"]);

export async function POST(request: Request) {
  const actor = await getActor();
  if (!actor) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (!canAccessModule(actor, "events.checkin")) {
    return NextResponse.json(
      { error: "Check-in access is required." },
      { status: 403 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  const parsed = bodySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }

  const payload = await verifyCardToken(parsed.data.token);
  if (!payload) {
    return NextResponse.json({ error: "Invalid or expired card code." }, { status: 410 });
  }

  const db = await getDb();
  const rows = await db
    .select({
      membershipId: memberships.id,
      status: memberships.status,
      memberNumber: memberships.memberNumber,
      userId: memberships.userId,
      memberChapterId: memberships.chapterId,
      memberName: user.name,
      chapterName: chapters.name,
    })
    .from(memberships)
    .innerJoin(user, eq(memberships.userId, user.id))
    .leftJoin(chapters, eq(memberships.chapterId, chapters.id))
    .where(
      and(
        eq(memberships.id, payload.membershipId),
        eq(memberships.userId, payload.userId),
      ),
    )
    .limit(1);
  const membership = rows[0];
  if (!membership) {
    return NextResponse.json({ error: "Membership not found." }, { status: 404 });
  }
  if (!allowedStatuses.has(membership.status)) {
    return NextResponse.json(
      { error: `Membership standing is ${membership.status.replaceAll("_", " ")}.` },
      { status: 403 },
    );
  }

  let eventTitle: string | undefined;
  if (parsed.data.eventId) {
    const eventRows = await db
      .select({ id: events.id, title: events.title, chapterId: events.chapterId })
      .from(events)
      .where(eq(events.id, parsed.data.eventId))
      .limit(1);
    const event = eventRows[0];
    if (!event) {
      return NextResponse.json({ error: "Event not found." }, { status: 404 });
    }
    if (!can(actor, "events.checkin", { chapterId: event.chapterId })) {
      return NextResponse.json({ error: "Event not found." }, { status: 404 });
    }
    if (
      !can(actor, "events.checkin", {
        chapterId: membership.memberChapterId,
      })
    ) {
      return NextResponse.json(
        { error: "Member belongs to another chapter." },
        { status: 403 },
      );
    }
    eventTitle = event.title;

    const registrationRows = await db
      .select({ id: eventRegistrations.id, status: eventRegistrations.status })
      .from(eventRegistrations)
      .where(
        and(
          eq(eventRegistrations.eventId, event.id),
          eq(eventRegistrations.userId, membership.userId),
        ),
      )
      .limit(1);
    const registration = registrationRows[0];
    if (!registration) {
      return NextResponse.json(
        { error: "Member is not registered for this event." },
        { status: 403 },
      );
    }
    if (registration.status !== "registered" && registration.status !== "attended") {
      return NextResponse.json(
        { error: `Registration status is ${registration.status}.` },
        { status: 403 },
      );
    }
  } else if (
    !can(actor, "events.checkin", {
      chapterId: membership.memberChapterId,
    })
  ) {
    return NextResponse.json(
      { error: "Member belongs to another chapter." },
      { status: 403 },
    );
  }

  if (parsed.data.eventId) {
    const existing = await db
      .select({ id: eventCheckins.id, checkedInAt: eventCheckins.checkedInAt })
      .from(eventCheckins)
      .where(
        and(
          eq(eventCheckins.eventId, parsed.data.eventId),
          eq(eventCheckins.userId, membership.userId),
        ),
      )
      .limit(1);

    if (existing[0]) {
      return NextResponse.json({
        ok: true,
        alreadyCheckedIn: true,
        checkedInAt: existing[0].checkedInAt.toISOString(),
        memberName: membership.memberName,
        memberNumber: membership.memberNumber,
        chapterName: membership.chapterName,
        status: membership.status,
        eventTitle,
      });
    }

    await db.insert(eventCheckins).values({
      id: `checkin_${crypto.randomUUID()}`,
      eventId: parsed.data.eventId,
      userId: membership.userId,
      checkedInAt: new Date(),
      checkedInBy: actor.userId,
      method: "qr",
    });
    await db
      .update(eventRegistrations)
      .set({ status: "attended", updatedAt: new Date() })
      .where(
        and(
          eq(eventRegistrations.eventId, parsed.data.eventId),
          eq(eventRegistrations.userId, membership.userId),
        ),
      );
  }

  const context = await requestAuditContext();
  await recordAuditEvent({
    actorUserId: actor.userId,
    action: "member.checkin",
    targetType: "membership",
    targetId: membership.membershipId,
    outcome: "success",
    requestId: context.requestId,
    ipHash: context.ipHash,
    userAgent: context.userAgent,
    metadata: { eventId: parsed.data.eventId ?? null },
  });

  return NextResponse.json({
    ok: true,
    alreadyCheckedIn: false,
    checkedInAt: new Date().toISOString(),
    memberName: membership.memberName,
    memberNumber: membership.memberNumber,
    chapterName: membership.chapterName,
    status: membership.status,
    eventTitle,
  });
}
