import { desc } from "drizzle-orm";

import { getDb, getEnv } from "@/lib/db/client";
import { adminAuditEvents } from "@/db/schema";

export type AuditOutcome = "success" | "failure";

export type AuditEventInput = {
  actorUserId: string | null;
  action: string;
  targetType: string;
  targetId?: string | null;
  outcome: AuditOutcome;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
  metadata?: Record<string, unknown> | null;
};

const SENSITIVE_KEY_PATTERN =
  /password|passwd|secret|token|authorization|cookie|api[_-]?key|credit|card|cvv|ssn|social|phone|address|email|note/i;

export function redactAuditMetadata(
  value: unknown,
  depth = 0,
): unknown {
  if (depth > 4) return "[truncated]";
  if (value === null || value === undefined) return value;
  if (typeof value === "string") {
    return value.length > 500 ? `${value.slice(0, 500)}…` : value;
  }
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) {
    return value.slice(0, 25).map((item) => redactAuditMetadata(item, depth + 1));
  }
  if (typeof value === "object") {
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      output[key] = SENSITIVE_KEY_PATTERN.test(key)
        ? "[redacted]"
        : redactAuditMetadata(item, depth + 1);
    }
    return output;
  }
  return String(value);
}

export async function hashClientIp(ip: string | null): Promise<string | null> {
  if (!ip) return null;
  const env = await getEnv();
  const salt = env.AUDIT_HASH_SALT ?? process.env.AUDIT_HASH_SALT;
  if (!salt) return null;
  const data = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export async function auditRequestContext(request: Request) {
  const ip =
    request.headers.get("cf-connecting-ip") ??
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    null;
  return {
    requestId:
      request.headers.get("x-request-id")?.slice(0, 200) ??
      `req_${crypto.randomUUID()}`,
    ipHash: await hashClientIp(ip),
    userAgent: request.headers.get("user-agent")?.slice(0, 300) ?? null,
  };
}

export async function recordAuditEvent(input: AuditEventInput): Promise<string> {
  const db = await getDb();
  const id = `audit_${crypto.randomUUID()}`;
  await db.insert(adminAuditEvents).values({
    id,
    actorUserId: input.actorUserId,
    action: input.action,
    targetType: input.targetType,
    targetId: input.targetId ?? null,
    outcome: input.outcome,
    requestId: input.requestId ?? null,
    ipHash: input.ipHash ?? null,
    userAgent: input.userAgent ?? null,
    metadataJson: JSON.stringify(
      redactAuditMetadata(input.metadata ?? {}) ?? {},
    ),
    createdAt: new Date(),
  });
  return id;
}

export async function listRecentAuditEvents(limit = 50) {
  const db = await getDb();
  return db
    .select()
    .from(adminAuditEvents)
    .orderBy(desc(adminAuditEvents.createdAt))
    .limit(Math.min(Math.max(limit, 1), 100));
}
