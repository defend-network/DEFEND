import { and, desc, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  announcements,
  cmsArticles,
  cmsPageBlocks,
  cmsPages,
  cmsRevisions,
} from "@/db/schema";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

export async function listCmsPages() {
  const db = await getDb();
  return db.select().from(cmsPages).orderBy(desc(cmsPages.updatedAt)).limit(100);
}

export async function listCmsArticles() {
  const db = await getDb();
  return db.select().from(cmsArticles).orderBy(desc(cmsArticles.updatedAt)).limit(100);
}

export async function listAnnouncements() {
  const db = await getDb();
  return db.select().from(announcements).orderBy(desc(announcements.createdAt)).limit(100);
}

export async function createCmsPage(input: {
  actor: ActorContext;
  title: string;
  slug?: string;
  text: string;
  seoTitle?: string;
  seoDescription?: string;
  publish: boolean;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const slug = slugify(input.slug || input.title);
  if (!slug) return { ok: false as const, error: "Enter a valid title." };
  const existing = await db
    .select({ id: cmsPages.id })
    .from(cmsPages)
    .where(eq(cmsPages.slug, slug))
    .limit(1);
  if (existing[0]) return { ok: false as const, error: "That slug is already in use." };
  const id = `page_${crypto.randomUUID()}`;
  const now = new Date();
  await db.insert(cmsPages).values({
    id,
    slug,
    title: input.title.trim(),
    seoTitle: input.seoTitle?.trim() || null,
    seoDescription: input.seoDescription?.trim() || null,
    status: input.publish ? "published" : "draft",
    publishedAt: input.publish ? now : null,
    updatedBy: input.actor.userId,
    createdAt: now,
    updatedAt: now,
  });
  await db.insert(cmsPageBlocks).values({
    id: `block_${crypto.randomUUID()}`,
    pageId: id,
    blockType: "rich_text",
    sortOrder: 0,
    contentJson: JSON.stringify({ text: input.text.trim() }),
    createdAt: now,
    updatedAt: now,
  });
  await db.insert(cmsRevisions).values({
    id: `rev_${crypto.randomUUID()}`,
    entityType: "cms_page",
    entityId: id,
    snapshotJson: JSON.stringify({ title: input.title, text: input.text }),
    createdBy: input.actor.userId,
    createdAt: now,
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: input.publish ? "cms.page.publish" : "cms.page.create",
    targetType: "cms_page",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { slug, published: input.publish },
  });
  return { ok: true as const, id, slug };
}

export async function createCmsArticle(input: {
  actor: ActorContext;
  title: string;
  slug?: string;
  excerpt: string;
  text: string;
  category?: string;
  seoTitle?: string;
  seoDescription?: string;
  publish: boolean;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const slug = slugify(input.slug || input.title);
  if (!slug) return { ok: false as const, error: "Enter a valid title." };
  const existing = await db
    .select({ id: cmsArticles.id })
    .from(cmsArticles)
    .where(eq(cmsArticles.slug, slug))
    .limit(1);
  if (existing[0]) return { ok: false as const, error: "That slug is already in use." };
  const id = `article_${crypto.randomUUID()}`;
  const now = new Date();
  await db.insert(cmsArticles).values({
    id,
    slug,
    title: input.title.trim(),
    excerpt: input.excerpt.trim(),
    contentJson: JSON.stringify({ text: input.text.trim() }),
    category: input.category || "news",
    status: input.publish ? "published" : "draft",
    seoTitle: input.seoTitle?.trim() || null,
    seoDescription: input.seoDescription?.trim() || null,
    publishedAt: input.publish ? now : null,
    authorId: input.actor.userId,
    createdAt: now,
    updatedAt: now,
  });
  await db.insert(cmsRevisions).values({
    id: `rev_${crypto.randomUUID()}`,
    entityType: "cms_article",
    entityId: id,
    snapshotJson: JSON.stringify({ title: input.title, text: input.text }),
    createdBy: input.actor.userId,
    createdAt: now,
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: input.publish ? "cms.article.publish" : "cms.article.create",
    targetType: "cms_article",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { slug, published: input.publish },
  });
  return { ok: true as const, id, slug };
}

export async function publishCmsEntity(input: {
  actor: ActorContext;
  entityType: "cms_page" | "cms_article";
  entityId: string;
  publish: boolean;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  if (input.entityType === "cms_page") {
    await db
      .update(cmsPages)
      .set({
        status: input.publish ? "published" : "draft",
        publishedAt: input.publish ? new Date() : null,
        updatedAt: new Date(),
        updatedBy: input.actor.userId,
      })
      .where(eq(cmsPages.id, input.entityId));
  } else {
    await db
      .update(cmsArticles)
      .set({
        status: input.publish ? "published" : "draft",
        publishedAt: input.publish ? new Date() : null,
        updatedAt: new Date(),
      })
      .where(eq(cmsArticles.id, input.entityId));
  }
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: input.publish ? "cms.publish" : "cms.unpublish",
    targetType: input.entityType,
    targetId: input.entityId,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {},
  });
  return { ok: true as const };
}

export async function createAnnouncement(input: {
  actor: ActorContext;
  title: string;
  body: string;
  visibility: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  const db = await getDb();
  const id = `announcement_${crypto.randomUUID()}`;
  await db.insert(announcements).values({
    id,
    title: input.title.trim(),
    body: input.body.trim(),
    visibility: input.visibility,
    publishedAt: new Date(),
    createdBy: input.actor.userId,
    createdAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "announcement.create",
    targetType: "announcement",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { visibility: input.visibility },
  });
  return { ok: true as const, id };
}

export async function listPublishedArticles(limit = 50) {
  const db = await getDb();
  return db
    .select()
    .from(cmsArticles)
    .where(eq(cmsArticles.status, "published"))
    .orderBy(desc(cmsArticles.publishedAt))
    .limit(limit);
}

export async function getPublishedArticle(slug: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(cmsArticles)
    .where(and(eq(cmsArticles.slug, slug), eq(cmsArticles.status, "published")))
    .limit(1);
  return rows[0] ?? null;
}

export async function getPublishedPage(slug: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(cmsPages)
    .where(and(eq(cmsPages.slug, slug), eq(cmsPages.status, "published")))
    .limit(1);
  const page = rows[0];
  if (!page) return null;
  const blocks = await db
    .select()
    .from(cmsPageBlocks)
    .where(eq(cmsPageBlocks.pageId, page.id))
    .orderBy(cmsPageBlocks.sortOrder);
  return { page, blocks };
}
