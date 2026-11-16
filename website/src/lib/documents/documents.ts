import { and, desc, eq, like, or, type SQL } from "drizzle-orm";

import { getDb, getEnv } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  documentPermissions,
  documentVersions,
  documents,
} from "@/db/schema";

const MAX_BYTES = 10 * 1024 * 1024;
const allowedTypes = new Set([
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/csv",
  "image/png",
  "image/jpeg",
  "image/webp",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]);

function safeFilename(value: string): string {
  return (value || "document")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120) || "document";
}

export async function listDocuments(input: { query?: string; category?: string } = {}) {
  const db = await getDb();
  const conditions: SQL[] = [];
  if (input.query?.trim()) {
    const pattern = `%${input.query.trim().slice(0, 120)}%`;
    conditions.push(
      or(
        like(documents.title, pattern),
        like(documents.filename, pattern),
        like(documents.category, pattern),
      ) as SQL,
    );
  }
  if (input.category && input.category !== "all") {
    conditions.push(eq(documents.category, input.category));
  }
  const where = conditions.length ? and(...conditions) : undefined;
  return db
    .select()
    .from(documents)
    .where(where)
    .orderBy(desc(documents.createdAt))
    .limit(100);
}

export async function uploadDocument(input: {
  actor: ActorContext;
  file: File;
  title: string;
  description?: string;
  category: string;
  visibility: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (input.file.size <= 0) return { ok: false as const, error: "Select a file." };
  if (input.file.size > MAX_BYTES) {
    return { ok: false as const, error: "File exceeds the 10 MB limit." };
  }
  if (!allowedTypes.has(input.file.type)) {
    return { ok: false as const, error: "This file type is not allowed." };
  }
  const visibility = ["admin", "chapter", "members", "public"].includes(input.visibility)
    ? input.visibility
    : "admin";
  const id = `doc_${crypto.randomUUID()}`;
  const filename = safeFilename(input.file.name);
  const key = `documents/${id}/${filename}`;
  const env = await getEnv();
  await env.DOCUMENTS.put(key, await input.file.arrayBuffer(), {
    httpMetadata: {
      contentType: input.file.type,
      contentDisposition: `attachment; filename="${filename}"`,
    },
  });
  const db = await getDb();
  await db.insert(documents).values({
    id,
    title: input.title.trim() || filename,
    description: input.description?.trim() || "",
    category: input.category || "general",
    r2Key: key,
    filename,
    mimeType: input.file.type,
    sizeBytes: input.file.size,
    version: 1,
    visibility,
    ownerUserId: input.actor.userId,
    status: "published",
    createdAt: new Date(),
    updatedAt: new Date(),
  });
  await db.insert(documentVersions).values({
    id: `docver_${crypto.randomUUID()}`,
    documentId: id,
    version: 1,
    r2Key: key,
    filename,
    sizeBytes: input.file.size,
    uploadedBy: input.actor.userId,
    createdAt: new Date(),
  });
  await db.insert(documentPermissions).values({
    id: `docperm_${crypto.randomUUID()}`,
    documentId: id,
    roleKey: "owner",
    scopeType: "global",
    scopeId: null,
    permission: "manage",
    createdAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "document.upload",
    targetType: "document",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { category: input.category, visibility, sizeBytes: input.file.size },
  });
  return { ok: true as const, id };
}

export async function getDocumentForDownload(documentId: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(documents)
    .where(and(eq(documents.id, documentId), eq(documents.status, "published")))
    .limit(1);
  return rows[0] ?? null;
}
