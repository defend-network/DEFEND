import {
  and,
  eq,
  inArray,
  like,
  or,
  type SQL,
} from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { decryptPii } from "@/lib/security/pii";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  chapters,
  directoryProfiles,
  memberProfiles,
  memberships,
  user,
} from "@/db/schema";

const eligibleStatuses = ["founding_access", "pending_payment", "active", "grace"];

function parseJson<T>(value: string | null | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    return { ...fallback, ...(JSON.parse(value) as Partial<T>) };
  } catch {
    return fallback;
  }
}

export type DirectoryEntry = {
  userId: string;
  displayName: string;
  chapterName: string | null;
  profession: string | null;
  businessName: string | null;
  skills: string[];
  volunteerInterests: string[];
  email: string | null;
  phone: string | null;
};

const defaultPreferences = {
  showChapter: true,
  showProfession: true,
  showBusiness: false,
  showSkills: true,
  showEmail: false,
  showPhone: false,
  showVolunteerInterests: true,
};

export async function getDirectory(input: {
  actor: ActorContext;
  query?: string;
  chapterId?: string;
}): Promise<DirectoryEntry[]> {
  const db = await getDb();
  const conditions: SQL[] = [
    eq(directoryProfiles.visible, true),
    inArray(memberships.status, eligibleStatuses),
  ];

  const query = input.query?.trim();
  if (query) {
    const pattern = `%${query.slice(0, 120)}%`;
    conditions.push(
      or(
        like(directoryProfiles.displayName, pattern),
        like(directoryProfiles.profession, pattern),
        like(directoryProfiles.businessName, pattern),
        like(directoryProfiles.skillsJson, pattern),
      ) as SQL,
    );
  }
  if (input.chapterId && input.chapterId !== "all") {
    conditions.push(eq(directoryProfiles.chapterId, input.chapterId));
  }

  const rows = await db
    .select({
      userId: directoryProfiles.userId,
      displayName: directoryProfiles.displayName,
      chapterName: chapters.name,
      profession: directoryProfiles.profession,
      businessName: directoryProfiles.businessName,
      skillsJson: directoryProfiles.skillsJson,
      volunteerInterestsJson: directoryProfiles.volunteerInterestsJson,
      contactPreferencesJson: directoryProfiles.contactPreferencesJson,
      email: user.email,
      phoneEncrypted: memberProfiles.phoneEncrypted,
    })
    .from(directoryProfiles)
    .innerJoin(user, eq(directoryProfiles.userId, user.id))
    .innerJoin(memberships, eq(memberships.userId, directoryProfiles.userId))
    .leftJoin(memberProfiles, eq(memberProfiles.userId, directoryProfiles.userId))
    .leftJoin(chapters, eq(directoryProfiles.chapterId, chapters.id))
    .where(and(...conditions))
    .limit(100);

  const entries: DirectoryEntry[] = [];
  for (const row of rows) {
    const preferences = parseJson(row.contactPreferencesJson, defaultPreferences);
    let skills: string[] = [];
    let volunteerInterests: string[] = [];
    try {
      const parsed = JSON.parse(row.skillsJson);
      if (Array.isArray(parsed)) skills = parsed.map(String);
    } catch {
      skills = [];
    }
    try {
      const parsed = JSON.parse(row.volunteerInterestsJson);
      if (Array.isArray(parsed)) volunteerInterests = parsed.map(String);
    } catch {
      volunteerInterests = [];
    }

    entries.push({
      userId: row.userId,
      displayName: row.displayName,
      chapterName: preferences.showChapter ? row.chapterName : null,
      profession: preferences.showProfession ? row.profession : null,
      businessName: preferences.showBusiness ? row.businessName : null,
      skills: preferences.showSkills ? skills : [],
      volunteerInterests: preferences.showVolunteerInterests
        ? volunteerInterests
        : [],
      email: preferences.showEmail ? row.email : null,
      phone:
        preferences.showPhone && row.phoneEncrypted
          ? await decryptPii(row.phoneEncrypted).catch(() => null)
          : null,
    });
  }

  return entries;
}
