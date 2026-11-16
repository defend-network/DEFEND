import { count, desc, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import type { ActorContext } from "@/lib/policy/permissions";
import { chapters, memberships, roleAssignments, user } from "@/db/schema";

export async function listChaptersWithCounts() {
  const db = await getDb();
  const rows = await db
    .select({
      id: chapters.id,
      name: chapters.name,
      slug: chapters.slug,
      county: chapters.county,
      state: chapters.state,
      status: chapters.status,
      description: chapters.description,
      contactEmail: chapters.contactEmail,
      createdAt: chapters.createdAt,
    })
    .from(chapters)
    .orderBy(desc(chapters.createdAt))
    .limit(100);

  return Promise.all(
    rows.map(async (chapter) => {
      const [members, leaders] = await Promise.all([
        db.select({ value: count() }).from(memberships).where(eq(memberships.chapterId, chapter.id)),
        db
          .select({ roleKey: roleAssignments.roleKey, name: user.name })
          .from(roleAssignments)
          .innerJoin(user, eq(roleAssignments.userId, user.id))
          .where(eq(roleAssignments.scopeId, chapter.id))
          .limit(20),
      ]);
      return { ...chapter, memberCount: members[0]?.value ?? 0, leaders };
    }),
  );
}

export async function createChapter(input: {
  actor: ActorContext;
  name: string;
  county: string;
  state: string;
  status: string;
  description?: string;
  contactEmail?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const slug = input.name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  if (!slug) return { ok: false as const, error: "Enter a valid chapter name." };
  const id = `chapter_${crypto.randomUUID()}`;
  await db.insert(chapters).values({
    id,
    slug,
    name: input.name.trim(),
    county: input.county.trim(),
    state: input.state.trim().toUpperCase(),
    status: input.status,
    description: input.description?.trim() || "",
    contactEmail: input.contactEmail?.trim() || null,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "chapter.create",
    targetType: "chapter",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { status: input.status },
  });
  return { ok: true as const, id };
}

export async function updateChapterStatus(input: {
  actor: ActorContext;
  chapterId: string;
  status: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const allowed = new Set(["operating", "in_development", "proposed", "inactive"]);
  if (!allowed.has(input.status)) return { ok: false as const, error: "Invalid chapter status." };
  const db = await getDb();
  const rows = await db.select().from(chapters).where(eq(chapters.id, input.chapterId)).limit(1);
  const chapter = rows[0];
  if (!chapter) return { ok: false as const, error: "Chapter not found." };
  await db.update(chapters).set({ status: input.status, updatedAt: new Date() }).where(eq(chapters.id, chapter.id));
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "chapter.status",
    targetType: "chapter",
    targetId: chapter.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { from: chapter.status, to: input.status },
  });
  return { ok: true as const };
}
