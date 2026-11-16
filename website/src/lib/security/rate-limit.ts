import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { requestRateLimits } from "@/db/schema";

export async function checkRateLimit(input: {
  key: string;
  limit: number;
  windowSeconds: number;
}): Promise<{ allowed: boolean; retryAfterSeconds?: number }> {
  const db = await getDb();
  const now = Date.now();
  const windowMs = input.windowSeconds * 1000;
  const cutoff = now - windowMs;
  const rows = await db
    .select()
    .from(requestRateLimits)
    .where(eq(requestRateLimits.key, input.key))
    .limit(1);
  const row = rows[0];

  if (!row) {
    await db.insert(requestRateLimits).values({
      key: input.key,
      count: 1,
      windowStart: now,
      expiresAt: now + windowMs,
    });
    return { allowed: true };
  }

  if (row.windowStart <= cutoff) {
    await db
      .update(requestRateLimits)
      .set({ count: 1, windowStart: now, expiresAt: now + windowMs })
      .where(eq(requestRateLimits.key, input.key));
    return { allowed: true };
  }

  if (row.count >= input.limit) {
    return {
      allowed: false,
      retryAfterSeconds: Math.max(
        1,
        Math.ceil((row.expiresAt - now) / 1000),
      ),
    };
  }

  await db
    .update(requestRateLimits)
    .set({ count: row.count + 1 })
    .where(eq(requestRateLimits.key, input.key));
  return { allowed: true };
}

export function rateLimitKey(scope: string, identifier: string): string {
  return `${scope}:${identifier.slice(0, 200)}`;
}
