import { desc, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { featureReleases } from "@/db/schema";

export const RELEASE_STATES = [
  "implemented",
  "tested",
  "staging_validated",
  "owner_reviewed",
  "deployed",
  "legally_authorized",
  "publicly_activated",
] as const;

export type ReleaseState = (typeof RELEASE_STATES)[number];

const RELEASE_STATE_ORDER: Record<ReleaseState, number> = {
  implemented: 1,
  tested: 2,
  staging_validated: 3,
  owner_reviewed: 4,
  deployed: 5,
  legally_authorized: 6,
  publicly_activated: 7,
};

export function isReleaseState(value: string): value is ReleaseState {
  return (RELEASE_STATES as readonly string[]).includes(value);
}

export function isPubliclyActivated(state: string): boolean {
  return state === "publicly_activated";
}

export function releaseStateAtLeast(
  state: string,
  minimum: ReleaseState,
): boolean {
  if (!isReleaseState(state)) return false;
  return RELEASE_STATE_ORDER[state] >= RELEASE_STATE_ORDER[minimum];
}

export async function listFeatureReleases() {
  const db = await getDb();
  return db
    .select()
    .from(featureReleases)
    .orderBy(desc(featureReleases.updatedAt));
}

export async function setFeatureReleaseState(input: {
  moduleKey: string;
  state: ReleaseState;
  notes?: string;
  updatedBy?: string | null;
}) {
  const db = await getDb();
  await db
    .update(featureReleases)
    .set({
      state: input.state,
      notes: input.notes?.trim() ?? "",
      updatedBy: input.updatedBy ?? null,
      updatedAt: new Date(),
    })
    .where(eq(featureReleases.moduleKey, input.moduleKey));
}
