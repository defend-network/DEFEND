import { and, count, desc, eq, gte, inArray } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { sendEmail } from "@/lib/email/send";
import { eventRegistrationEmail, volunteerRegistrationEmail } from "@/lib/email/templates";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  chapters,
  eventRegistrations,
  events,
  memberships,
  user,
  volunteerOpportunities,
  volunteerRegistrations,
} from "@/db/schema";

const eligibleStatuses = ["founding_access", "pending_payment", "active", "grace"];

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

export async function listAdminEvents() {
  const db = await getDb();
  return db
    .select({
      id: events.id,
      slug: events.slug,
      title: events.title,
      startsAt: events.startsAt,
      locationName: events.locationName,
      capacity: events.capacity,
      status: events.status,
      chapterId: events.chapterId,
    })
    .from(events)
    .orderBy(desc(events.startsAt))
    .limit(100);
}

export async function createEvent(input: {
  actor: ActorContext;
  title: string;
  summary: string;
  description: string;
  startsAt: Date;
  locationName?: string | null;
  address?: string | null;
  capacity?: number | null;
  feeCents?: number | null;
  familyFriendly?: boolean;
  status: "draft" | "published";
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const slugBase = slugify(input.title);
  if (!slugBase) return { ok: false as const, error: "Enter a valid event title." };
  const existing = await db
    .select({ id: events.id })
    .from(events)
    .where(eq(events.slug, slugBase))
    .limit(1);
  const slug = existing.length ? `${slugBase}-${crypto.randomUUID().slice(0, 6)}` : slugBase;
  const id = `event_${crypto.randomUUID()}`;

  await db.insert(events).values({
    id,
    slug,
    title: input.title.trim(),
    summary: input.summary.trim(),
    description: input.description.trim(),
    chapterId: "chapter_pasco",
    startsAt: input.startsAt,
    locationName: input.locationName?.trim() || null,
    address: input.address?.trim() || null,
    capacity: input.capacity && input.capacity > 0 ? input.capacity : null,
    feeCents: input.feeCents && input.feeCents > 0 ? input.feeCents : 0,
    familyFriendly: Boolean(input.familyFriendly),
    status: input.status,
    createdBy: input.actor.userId,
    createdAt: new Date(),
    updatedAt: new Date(),
  });

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "event.create",
    targetType: "event",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { status: input.status },
  });

  return { ok: true as const, eventId: id, slug };
}

export async function listPublishedEvents(limit = 50) {
  const db = await getDb();
  return db
    .select({
      id: events.id,
      slug: events.slug,
      title: events.title,
      summary: events.summary,
      startsAt: events.startsAt,
      locationName: events.locationName,
      capacity: events.capacity,
      feeCents: events.feeCents,
      familyFriendly: events.familyFriendly,
      status: events.status,
      chapterName: chapters.name,
    })
    .from(events)
    .leftJoin(chapters, eq(events.chapterId, chapters.id))
    .where(and(eq(events.status, "published"), gte(events.startsAt, new Date())))
    .orderBy(events.startsAt)
    .limit(limit);
}

export async function getEventBySlug(slug: string) {
  const db = await getDb();
  const rows = await db
    .select({
      id: events.id,
      slug: events.slug,
      title: events.title,
      summary: events.summary,
      description: events.description,
      startsAt: events.startsAt,
      endsAt: events.endsAt,
      locationName: events.locationName,
      address: events.address,
      capacity: events.capacity,
      feeCents: events.feeCents,
      familyFriendly: events.familyFriendly,
      status: events.status,
      chapterName: chapters.name,
    })
    .from(events)
    .leftJoin(chapters, eq(events.chapterId, chapters.id))
    .where(and(eq(events.slug, slug), eq(events.status, "published")))
    .limit(1);
  return rows[0] ?? null;
}

export async function getMemberEventState(userId: string) {
  const db = await getDb();
  const membershipRows = await db
    .select({ status: memberships.status })
    .from(memberships)
    .where(eq(memberships.userId, userId))
    .limit(1);
  const membershipStatus = membershipRows[0]?.status;
  const registrations = await db
    .select({
      eventId: eventRegistrations.eventId,
      status: eventRegistrations.status,
      title: events.title,
      slug: events.slug,
      startsAt: events.startsAt,
    })
    .from(eventRegistrations)
    .innerJoin(events, eq(eventRegistrations.eventId, events.id))
    .where(eq(eventRegistrations.userId, userId))
    .orderBy(events.startsAt)
    .limit(50);
  return { membershipStatus, registrations };
}

export async function registerForEvent(input: {
  userId: string;
  eventId: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const membershipRows = await db
    .select({ status: memberships.status })
    .from(memberships)
    .where(eq(memberships.userId, input.userId))
    .limit(1);
  const membership = membershipRows[0];
  if (!membership || !eligibleStatuses.includes(membership.status)) {
    return { ok: false as const, error: "Your membership is not currently eligible to register." };
  }

  const eventRows = await db
    .select()
    .from(events)
    .where(and(eq(events.id, input.eventId), eq(events.status, "published")))
    .limit(1);
  const event = eventRows[0];
  if (!event) return { ok: false as const, error: "Event not found." };
  if (event.startsAt.getTime() < Date.now()) {
    return { ok: false as const, error: "Registration is closed for this event." };
  }

  const existing = await db
    .select({ id: eventRegistrations.id, status: eventRegistrations.status })
    .from(eventRegistrations)
    .where(
      and(
        eq(eventRegistrations.eventId, event.id),
        eq(eventRegistrations.userId, input.userId),
      ),
    )
    .limit(1);
  if (existing[0] && existing[0].status !== "cancelled") {
    return { ok: true as const, status: existing[0].status, alreadyRegistered: true };
  }

  let status = "registered";
  if (event.capacity) {
    const countRows = await db
      .select({ value: count() })
      .from(eventRegistrations)
      .where(
        and(
          eq(eventRegistrations.eventId, event.id),
          inArray(eventRegistrations.status, ["registered", "attended"]),
        ),
      );
    if ((countRows[0]?.value ?? 0) >= event.capacity) {
      status = "waitlisted";
    }
  }

  if (existing[0]) {
    await db
      .update(eventRegistrations)
      .set({ status, updatedAt: new Date() })
      .where(eq(eventRegistrations.id, existing[0].id));
  } else {
    await db.insert(eventRegistrations).values({
      id: `reg_${crypto.randomUUID()}`,
      eventId: event.id,
      userId: input.userId,
      status,
      createdAt: new Date(),
      updatedAt: new Date(),
    });
  }

  const userRows = await db
    .select({ name: user.name, email: user.email })
    .from(user)
    .where(eq(user.id, input.userId))
    .limit(1);
  const member = userRows[0];
  if (member) {
    await sendEmail(
      eventRegistrationEmail({
        to: member.email,
        name: member.name,
        eventTitle: event.title,
        startsAt: event.startsAt,
        status,
      }),
    );
  }

  await recordAuditEvent({
    actorUserId: input.userId,
    action: "event.register",
    targetType: "event",
    targetId: event.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { status },
  });

  return { ok: true as const, status, alreadyRegistered: false };
}

export async function listVolunteerOpportunities() {
  const db = await getDb();
  return db
    .select({
      id: volunteerOpportunities.id,
      title: volunteerOpportunities.title,
      description: volunteerOpportunities.description,
      slots: volunteerOpportunities.slots,
      skillsJson: volunteerOpportunities.skillsJson,
      availability: volunteerOpportunities.availability,
      isInstructorRole: volunteerOpportunities.isInstructorRole,
      status: volunteerOpportunities.status,
      chapterId: volunteerOpportunities.chapterId,
    })
    .from(volunteerOpportunities)
    .where(eq(volunteerOpportunities.status, "published"))
    .orderBy(desc(volunteerOpportunities.createdAt))
    .limit(50);
}

export async function createVolunteerOpportunity(input: {
  actor: ActorContext;
  title: string;
  description: string;
  slots?: number | null;
  skills?: string;
  availability?: string;
  isInstructorRole?: boolean;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `vol_${crypto.randomUUID()}`;
  await db.insert(volunteerOpportunities).values({
    id,
    chapterId: "chapter_pasco",
    title: input.title.trim(),
    description: input.description.trim(),
    slots: input.slots && input.slots > 0 ? input.slots : null,
    skillsJson: JSON.stringify(
      input.skills ? input.skills.split(",").map((skill) => skill.trim()).filter(Boolean) : [],
    ),
    availability: input.availability?.trim() || null,
    isInstructorRole: Boolean(input.isInstructorRole),
    status: "published",
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "volunteer.create",
    targetType: "volunteer_opportunity",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {},
  });
  return { ok: true as const, id };
}

export async function registerForVolunteer(input: {
  userId: string;
  opportunityId: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const opportunityRows = await db
    .select()
    .from(volunteerOpportunities)
    .where(
      and(
        eq(volunteerOpportunities.id, input.opportunityId),
        eq(volunteerOpportunities.status, "published"),
      ),
    )
    .limit(1);
  const opportunity = opportunityRows[0];
  if (!opportunity) return { ok: false as const, error: "Opportunity not found." };

  const existing = await db
    .select({ id: volunteerRegistrations.id })
    .from(volunteerRegistrations)
    .where(
      and(
        eq(volunteerRegistrations.opportunityId, opportunity.id),
        eq(volunteerRegistrations.userId, input.userId),
      ),
    )
    .limit(1);
  if (existing[0]) {
    return { ok: true as const, alreadyRegistered: true };
  }

  await db.insert(volunteerRegistrations).values({
    id: `vreg_${crypto.randomUUID()}`,
    opportunityId: opportunity.id,
    userId: input.userId,
    status: "registered",
    createdAt: new Date(),
  });

  const userRows = await db
    .select({ name: user.name, email: user.email })
    .from(user)
    .where(eq(user.id, input.userId))
    .limit(1);
  const member = userRows[0];
  if (member) {
    await sendEmail(
      volunteerRegistrationEmail({
        to: member.email,
        name: member.name,
        opportunityTitle: opportunity.title,
      }),
    );
  }

  await recordAuditEvent({
    actorUserId: input.userId,
    action: "volunteer.register",
    targetType: "volunteer_opportunity",
    targetId: opportunity.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {},
  });

  return { ok: true as const, alreadyRegistered: false };
}

