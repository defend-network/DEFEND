import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { encryptPii, decryptPii } from "@/lib/security/pii";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  chapters,
  directoryProfiles,
  memberProfiles,
  memberships,
} from "@/db/schema";

export type DirectoryPreferences = {
  showChapter: boolean;
  showProfession: boolean;
  showBusiness: boolean;
  showSkills: boolean;
  showEmail: boolean;
  showPhone: boolean;
  showVolunteerInterests: boolean;
};

export type NotificationPreferences = {
  membership: boolean;
  events: boolean;
  newsletter: boolean;
};

const defaultDirectoryPreferences: DirectoryPreferences = {
  showChapter: true,
  showProfession: true,
  showBusiness: false,
  showSkills: true,
  showEmail: false,
  showPhone: false,
  showVolunteerInterests: true,
};

const defaultNotificationPreferences: NotificationPreferences = {
  membership: true,
  events: true,
  newsletter: false,
};

function parseJson<T>(value: string | null | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    return { ...fallback, ...(JSON.parse(value) as Partial<T>) };
  } catch {
    return fallback;
  }
}

export async function getMemberAccount(userId: string) {
  const db = await getDb();
  const profileRows = await db
    .select()
    .from(memberProfiles)
    .where(eq(memberProfiles.userId, userId))
    .limit(1);
  const membershipRows = await db
    .select()
    .from(memberships)
    .where(eq(memberships.userId, userId))
    .limit(1);
  const directoryRows = await db
    .select()
    .from(directoryProfiles)
    .where(eq(directoryProfiles.userId, userId))
    .limit(1);
  const chapterRows = await db
    .select({ id: chapters.id, name: chapters.name, status: chapters.status })
    .from(chapters);

  const profile = profileRows[0];
  const membership = membershipRows[0];
  const directory = directoryRows[0];

  return {
    profile,
    membership,
    directory,
    chapters: chapterRows,
    phone: profile?.phoneEncrypted
      ? await decryptPii(profile.phoneEncrypted).catch(() => null)
      : null,
    directoryPreferences: parseJson<DirectoryPreferences>(
      directory?.contactPreferencesJson,
      defaultDirectoryPreferences,
    ),
    notificationPreferences: parseJson<NotificationPreferences>(
      profile?.notificationPreferencesJson,
      defaultNotificationPreferences,
    ),
  };
}

export async function updateMemberAccount(input: {
  userId: string;
  actor: ActorContext;
  preferredName?: string | null;
  phone?: string | null;
  city?: string | null;
  state?: string | null;
  postalCode?: string | null;
  directoryVisible: boolean;
  familyParticipation: boolean;
  profession?: string | null;
  businessName?: string | null;
  skills?: string | null;
  volunteerInterests: string[];
  directoryPreferences: DirectoryPreferences;
  notificationPreferences: NotificationPreferences;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (input.actor.userId !== input.userId) {
    return { ok: false, error: "You may only update your own profile." };
  }

  const db = await getDb();
  const profileRows = await db
    .select()
    .from(memberProfiles)
    .where(eq(memberProfiles.userId, input.userId))
    .limit(1);
  const profile = profileRows[0];
  if (!profile) return { ok: false, error: "Member profile not found." };

  const phoneEncrypted = input.phone?.trim()
    ? await encryptPii(input.phone.trim())
    : null;

  await db
    .update(memberProfiles)
    .set({
      preferredName: input.preferredName?.trim() || null,
      phoneEncrypted,
      city: input.city?.trim() || null,
      state: input.state?.trim().toUpperCase() || null,
      postalCode: input.postalCode?.trim() || null,
      notificationPreferencesJson: JSON.stringify(input.notificationPreferences),
      familyParticipation: input.familyParticipation,
      updatedAt: new Date(),
    })
    .where(eq(memberProfiles.userId, input.userId));

  const directoryValues = {
    displayName:
      input.preferredName?.trim() || profile.legalFirstName || "DEFEND member",
    chapterId: profile.chapterId,
    profession: input.profession?.trim() || null,
    businessName: input.businessName?.trim() || null,
    skillsJson: JSON.stringify(
      input.skills
        ? input.skills.split(",").map((value) => value.trim()).filter(Boolean)
        : [],
    ),
    expertiseJson: JSON.stringify([]),
    volunteerInterestsJson: JSON.stringify(input.volunteerInterests),
    visible: input.directoryVisible,
    contactPreferencesJson: JSON.stringify(input.directoryPreferences),
    updatedAt: new Date(),
  };

  await db
    .insert(directoryProfiles)
    .values({
      id: `dir_${crypto.randomUUID()}`,
      userId: input.userId,
      ...directoryValues,
    })
    .onConflictDoUpdate({
      target: directoryProfiles.userId,
      set: directoryValues,
    });

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "member.profile.update",
    targetType: "member_profile",
    targetId: profile.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {
      directoryVisible: input.directoryVisible,
      notificationPreferences: input.notificationPreferences,
    },
  });

  return { ok: true };
}

