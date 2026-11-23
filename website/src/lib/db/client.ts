import { getCloudflareContext } from "@opennextjs/cloudflare";
import type { D1Database, R2Bucket } from "@cloudflare/workers-types";
import { drizzle } from "drizzle-orm/d1";

import * as schema from "@/db/schema";

export type AppEnv = {
  DB: D1Database;
  DOCUMENTS: R2Bucket;
  MEDIA: R2Bucket;
  APP_ENV?: string;
  APP_URL?: string;
  BETTER_AUTH_SECRET?: string;
  AUDIT_HASH_SALT?: string;
  PAYMENTS_MODE?: string;
  PAYMENTS_LIVE_APPROVED?: string;
  DONATIONS_ENABLED?: string;
};

export async function getEnv(): Promise<AppEnv> {
  const { env } = await getCloudflareContext({ async: true });
  return env as unknown as AppEnv;
}

export async function getDb() {
  const env = await getEnv();
  return drizzle(env.DB, { schema });
}

export type Database = Awaited<ReturnType<typeof getDb>>;
