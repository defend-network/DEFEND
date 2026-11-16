import { and, desc, eq, ne } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import type { ActorContext } from "@/lib/policy/permissions";
import { programs } from "@/db/schema";

export async function listPrograms() {
  const db = await getDb();
  return db.select().from(programs).orderBy(desc(programs.createdAt)).limit(100);
}

export async function createProgram(input: {
  actor: ActorContext;
  title: string;
  summary?: string;
  description?: string;
  status: string;
  capacity?: number | null;
  feeCents?: number | null;
  eligibility?: string;
  familyFriendly?: boolean;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const slug = input.title.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  if (!slug) return { ok: false as const, error: "Enter a valid program title." };
  const existing = await db.select({ id: programs.id }).from(programs).where(eq(programs.slug, slug)).limit(1);
  if (existing[0]) return { ok: false as const, error: "A program with that slug already exists." };
  const id = `program_${crypto.randomUUID()}`;
  await db.insert(programs).values({
    id,
    slug,
    title: input.title.trim(),
    summary: input.summary?.trim() || "",
    description: input.description?.trim() || "",
    status: input.status,
    capacity: input.capacity && input.capacity > 0 ? input.capacity : null,
    feeCents: input.feeCents && input.feeCents > 0 ? Math.round(input.feeCents) : 0,
    eligibility: input.eligibility?.trim() || null,
    familyFriendly: Boolean(input.familyFriendly),
    youthSafeguardingRequired: false,
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "program.create",
    targetType: "program",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { status: input.status, familyFriendly: Boolean(input.familyFriendly) },
  });
  return { ok: true as const, id };
}

export async function listPublicPrograms() {
  const db = await getDb();
  return db
    .select()
    .from(programs)
    .where(
      and(
        ne(programs.status, "draft"),
        ne(programs.status, "archived"),
      ),
    )
    .orderBy(programs.title)
    .limit(100);
}

export async function getPublicProgram(slug: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(programs)
    .where(and(eq(programs.slug, slug), ne(programs.status, "draft")))
    .limit(1);
  return rows[0] ?? null;
}
