import {
  and,
  count,
  desc,
  eq,
  like,
  or,
  type SQL,
} from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import {
  createInvitation,
  generateInvitationToken,
  hashInvitationToken,
} from "@/lib/auth/invitations";
import { decryptPii, encryptPii } from "@/lib/security/pii";
import { sendEmail } from "@/lib/email/send";
import {
  applicationApprovedEmail,
  applicationDeniedEmail,
  applicationNeedsInfoEmail,
} from "@/lib/email/templates";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  applicationReviews,
  applicationUpdateTokens,
  chapters,
  invitations,
  membershipApplications,
} from "@/db/schema";

export type ApplicationStatus =
  | "submitted"
  | "under_review"
  | "needs_info"
  | "approved"
  | "denied"
  | "withdrawn"
  | "expired"
  | "activated";

export type ApplicationListFilter = {
  status?: ApplicationStatus | "all";
  query?: string;
  limit?: number;
  offset?: number;
};

function appBaseUrl(): string {
  return (process.env.APP_URL ?? "http://localhost:3000").replace(/\/$/, "");
}

function activationUrl(token: string): string {
  return `${appBaseUrl()}/activate#token=${encodeURIComponent(token)}`;
}

function applicationUpdateUrl(token: string): string {
  return `${appBaseUrl()}/apply/update#token=${encodeURIComponent(token)}`;
}

function splitName(value: string): { first: string; last: string } {
  const parts = value.trim().split(/\s+/);
  if (parts.length <= 1) return { first: value.trim(), last: "" };
  return { first: parts.slice(0, -1).join(" "), last: parts.at(-1) ?? "" };
}

export async function listApplications(filter: ApplicationListFilter = {}) {
  const db = await getDb();
  const limit = Math.min(Math.max(filter.limit ?? 25, 1), 100);
  const offset = Math.max(filter.offset ?? 0, 0);
  const conditions: SQL[] = [];

  if (filter.status && filter.status !== "all") {
    conditions.push(eq(membershipApplications.status, filter.status));
  }

  const query = filter.query?.trim();
  if (query) {
    const pattern = `%${query.slice(0, 120)}%`;
    conditions.push(
      or(
        like(membershipApplications.applicationNumber, pattern),
        like(membershipApplications.legalName, pattern),
        like(membershipApplications.email, pattern),
      ) as SQL,
    );
  }

  const where = conditions.length ? and(...conditions) : undefined;

  const [items, totalRows] = await Promise.all([
    db
      .select({
        id: membershipApplications.id,
        applicationNumber: membershipApplications.applicationNumber,
        legalName: membershipApplications.legalName,
        preferredName: membershipApplications.preferredName,
        email: membershipApplications.email,
        city: membershipApplications.city,
        state: membershipApplications.state,
        status: membershipApplications.status,
        submittedAt: membershipApplications.submittedAt,
        reviewedAt: membershipApplications.reviewedAt,
        desiredChapterId: membershipApplications.desiredChapterId,
      })
      .from(membershipApplications)
      .where(where)
      .orderBy(desc(membershipApplications.submittedAt))
      .limit(limit)
      .offset(offset),
    db.select({ value: count() }).from(membershipApplications).where(where),
  ]);

  return {
    items,
    total: totalRows[0]?.value ?? 0,
    limit,
    offset,
  };
}

export async function countApplicationsByStatus(status: ApplicationStatus) {
  const db = await getDb();
  const rows = await db
    .select({ value: count() })
    .from(membershipApplications)
    .where(eq(membershipApplications.status, status));
  return rows[0]?.value ?? 0;
}

export async function getApplicationDetail(applicationId: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(membershipApplications)
    .where(eq(membershipApplications.id, applicationId))
    .limit(1);
  const application = rows[0];
  if (!application) return null;

  let phone: string | null = null;
  let decisionNotes: string | null = null;
  let infoRequest: string | null = null;
  if (application.phoneEncrypted) {
    phone = await decryptPii(application.phoneEncrypted).catch(() => null);
  }
  if (application.decisionNotesEncrypted) {
    decisionNotes = await decryptPii(application.decisionNotesEncrypted).catch(
      () => null,
    );
  }
  if (application.infoRequestEncrypted) {
    infoRequest = await decryptPii(application.infoRequestEncrypted).catch(
      () => null,
    );
  }

  const chapterRows = await db
    .select({ id: chapters.id, name: chapters.name, slug: chapters.slug })
    .from(chapters);

  const reviews = await db
    .select({
      id: applicationReviews.id,
      action: applicationReviews.action,
      createdAt: applicationReviews.createdAt,
      reviewerId: applicationReviews.reviewerId,
    })
    .from(applicationReviews)
    .where(eq(applicationReviews.applicationId, applicationId))
    .orderBy(desc(applicationReviews.createdAt))
    .limit(20);

  return {
    application: {
      ...application,
      phone,
      decisionNotes,
      infoRequest,
    },
    chapters: chapterRows,
    reviews,
  };
}

async function setNotificationStatus(
  applicationId: string,
  status: string,
) {
  const db = await getDb();
  await db
    .update(membershipApplications)
    .set({ notificationStatus: status, updatedAt: new Date() })
    .where(eq(membershipApplications.id, applicationId));
}

export async function approveApplication(input: {
  applicationId: string;
  actor: ActorContext;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}): Promise<{
  ok: boolean;
  error?: string;
  activationUrl?: string;
  invitationId?: string;
  emailStatus?: string;
}> {
  const db = await getDb();
  const rows = await db
    .select()
    .from(membershipApplications)
    .where(eq(membershipApplications.id, input.applicationId))
    .limit(1);
  const application = rows[0];
  if (!application) return { ok: false, error: "Application not found." };
  if (application.status === "approved" || application.status === "activated") {
    return { ok: false, error: "Application is already approved." };
  }
  if (application.status === "denied") {
    return { ok: false, error: "A denied application cannot be approved." };
  }

  const notes = input.notes?.trim() || null;
  const encodedNotes = notes ? await encryptPii(notes) : null;
  const invitation = await createInvitation({
    email: application.email,
    createdBy: input.actor.userId,
    applicationId: application.id,
    intendedRole: "member",
  });
  const url = activationUrl(invitation.token);

  await db
    .update(membershipApplications)
    .set({
      status: "approved",
      reviewedAt: new Date(),
      reviewedBy: input.actor.userId,
      decisionNotesEncrypted: encodedNotes,
      notificationStatus: "pending",
      updatedAt: new Date(),
    })
    .where(eq(membershipApplications.id, application.id));

  await db.insert(applicationReviews).values({
    id: `review_${crypto.randomUUID()}`,
    applicationId: application.id,
    reviewerId: input.actor.userId,
    action: "approved",
    notesEncrypted: encodedNotes,
    createdAt: new Date(),
  });

  const email = await sendEmail(
    applicationApprovedEmail({
      to: application.email,
      name: application.preferredName || application.legalName,
      activationUrl: url,
      expiresAt: invitation.expiresAt,
    }),
  );

  await db
    .update(invitations)
    .set({
      deliveryStatus: email.status,
      deliveryError: email.error ?? null,
    })
    .where(eq(invitations.id, invitation.invitationId));

  await setNotificationStatus(application.id, email.status);

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "application.approve",
    targetType: "membership_application",
    targetId: application.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: {
      invitationId: invitation.invitationId,
      emailStatus: email.status,
    },
  });

  return {
    ok: true,
    activationUrl: url,
    invitationId: invitation.invitationId,
    emailStatus: email.status,
  };
}

export async function denyApplication(input: {
  applicationId: string;
  actor: ActorContext;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}): Promise<{ ok: boolean; error?: string; emailStatus?: string }> {
  const db = await getDb();
  const rows = await db
    .select()
    .from(membershipApplications)
    .where(eq(membershipApplications.id, input.applicationId))
    .limit(1);
  const application = rows[0];
  if (!application) return { ok: false, error: "Application not found." };
  if (application.status === "approved" || application.status === "activated") {
    return { ok: false, error: "An approved application cannot be denied." };
  }

  const notes = input.notes?.trim() || null;
  const encodedNotes = notes ? await encryptPii(notes) : null;
  await db
    .update(membershipApplications)
    .set({
      status: "denied",
      reviewedAt: new Date(),
      reviewedBy: input.actor.userId,
      decisionNotesEncrypted: encodedNotes,
      notificationStatus: "pending",
      updatedAt: new Date(),
    })
    .where(eq(membershipApplications.id, application.id));

  await db.insert(applicationReviews).values({
    id: `review_${crypto.randomUUID()}`,
    applicationId: application.id,
    reviewerId: input.actor.userId,
    action: "denied",
    notesEncrypted: encodedNotes,
    createdAt: new Date(),
  });

  const email = await sendEmail(
    applicationDeniedEmail({
      to: application.email,
      name: application.preferredName || application.legalName,
    }),
  );
  await setNotificationStatus(application.id, email.status);

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "application.deny",
    targetType: "membership_application",
    targetId: application.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { emailStatus: email.status },
  });

  return { ok: true, emailStatus: email.status };
}

export async function requestApplicationInfo(input: {
  applicationId: string;
  actor: ActorContext;
  message: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}): Promise<{
  ok: boolean;
  error?: string;
  updateUrl?: string;
  emailStatus?: string;
}> {
  const message = input.message.trim();
  if (message.length < 5) {
    return { ok: false, error: "Enter a message for the applicant." };
  }

  const db = await getDb();
  const rows = await db
    .select()
    .from(membershipApplications)
    .where(eq(membershipApplications.id, input.applicationId))
    .limit(1);
  const application = rows[0];
  if (!application) return { ok: false, error: "Application not found." };
  if (application.status === "approved" || application.status === "activated") {
    return { ok: false, error: "An approved application cannot be reopened." };
  }

  const encodedMessage = await encryptPii(message);
  const { token } = generateInvitationToken();
  const tokenHash = await hashInvitationToken(token);
  const expiresAt = new Date(Date.now() + 72 * 60 * 60 * 1000);
  const url = applicationUpdateUrl(token);

  await db.insert(applicationUpdateTokens).values({
    id: `au_${crypto.randomUUID()}`,
    applicationId: application.id,
    tokenHash,
    expiresAt,
    createdBy: input.actor.userId,
    createdAt: new Date(),
  });

  await db
    .update(membershipApplications)
    .set({
      status: "needs_info",
      infoRequestEncrypted: encodedMessage,
      infoRequestedAt: new Date(),
      notificationStatus: "pending",
      updatedAt: new Date(),
    })
    .where(eq(membershipApplications.id, application.id));

  await db.insert(applicationReviews).values({
    id: `review_${crypto.randomUUID()}`,
    applicationId: application.id,
    reviewerId: input.actor.userId,
    action: "needs_info",
    notesEncrypted: encodedMessage,
    createdAt: new Date(),
  });

  const email = await sendEmail(
    applicationNeedsInfoEmail({
      to: application.email,
      name: application.preferredName || application.legalName,
      message,
      updateUrl: url,
    }),
  );
  await setNotificationStatus(application.id, email.status);

  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "application.request_info",
    targetType: "membership_application",
    targetId: application.id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { emailStatus: email.status },
  });

  return { ok: true, updateUrl: url, emailStatus: email.status };
}

export async function getApplicationUpdate(
  token: string,
): Promise<{
  ok: boolean;
  application?: {
    id: string;
    applicationNumber: string;
    legalName: string;
    preferredName: string | null;
    email: string;
    city: string | null;
    state: string | null;
    postalCode: string | null;
    desiredChapterId: string | null;
    status: string;
    infoRequest: string | null;
  };
  error?: string;
}> {
  if (!token || token.length > 512) return { ok: false, error: "Unavailable." };
  const db = await getDb();
  const tokenHash = await hashInvitationToken(token);
  const tokenRows = await db
    .select()
    .from(applicationUpdateTokens)
    .where(eq(applicationUpdateTokens.tokenHash, tokenHash))
    .limit(1);
  const updateToken = tokenRows[0];
  if (
    !updateToken ||
    updateToken.consumedAt ||
    updateToken.expiresAt.getTime() <= Date.now()
  ) {
    return { ok: false, error: "This update link is unavailable." };
  }
  const rows = await db
    .select()
    .from(membershipApplications)
    .where(eq(membershipApplications.id, updateToken.applicationId))
    .limit(1);
  const application = rows[0];
  if (!application) return { ok: false, error: "Application not found." };
  const infoRequest = application.infoRequestEncrypted
    ? await decryptPii(application.infoRequestEncrypted).catch(() => null)
    : null;

  return {
    ok: true,
    application: {
      id: application.id,
      applicationNumber: application.applicationNumber,
      legalName: application.legalName,
      preferredName: application.preferredName,
      email: application.email,
      city: application.city,
      state: application.state,
      postalCode: application.postalCode,
      desiredChapterId: application.desiredChapterId,
      status: application.status,
      infoRequest,
    },
  };
}

export async function updateApplicationWithToken(input: {
  token: string;
  preferredName?: string | null;
  email: string;
  city: string;
  state: string;
  postalCode?: string | null;
  interests: string[];
  skills?: string | null;
  volunteerInterests: string[];
  programInterests: string[];
}): Promise<{ ok: boolean; error?: string }> {
  const tokenHash = await hashInvitationToken(input.token);
  const db = await getDb();
  const tokenRows = await db
    .select()
    .from(applicationUpdateTokens)
    .where(eq(applicationUpdateTokens.tokenHash, tokenHash))
    .limit(1);
  const updateToken = tokenRows[0];
  if (
    !updateToken ||
    updateToken.consumedAt ||
    updateToken.expiresAt.getTime() <= Date.now()
  ) {
    return { ok: false, error: "This update link is unavailable." };
  }

  const rows = await db
    .select()
    .from(membershipApplications)
    .where(eq(membershipApplications.id, updateToken.applicationId))
    .limit(1);
  const application = rows[0];
  if (!application) return { ok: false, error: "Application not found." };
  if (application.status !== "needs_info") {
    return { ok: false, error: "This application is not awaiting information." };
  }

  await db
    .update(membershipApplications)
    .set({
      preferredName: input.preferredName?.trim() || null,
      email: input.email.toLowerCase(),
      city: input.city.trim(),
      state: input.state.trim().toUpperCase(),
      postalCode: input.postalCode?.trim() || null,
      interestsJson: JSON.stringify(input.interests),
      skillsJson: JSON.stringify(input.skills ? [input.skills] : []),
      volunteerInterestsJson: JSON.stringify(input.volunteerInterests),
      programInterestsJson: JSON.stringify(input.programInterests),
      status: "under_review",
      infoRequestEncrypted: null,
      infoRequestedAt: null,
      updatedAt: new Date(),
    })
    .where(eq(membershipApplications.id, application.id));

  await db
    .update(applicationUpdateTokens)
    .set({ consumedAt: new Date() })
    .where(eq(applicationUpdateTokens.id, updateToken.id));

  return { ok: true };
}

export { splitName };
