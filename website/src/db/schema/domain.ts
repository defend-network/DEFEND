import { sql } from "drizzle-orm";
import {
  index,
  integer,
  sqliteTable,
  text,
  uniqueIndex,
} from "drizzle-orm/sqlite-core";

import { user } from "./auth";

const timestampDefault = sql`(cast(unixepoch('subsecond') * 1000 as integer))`;

export const chapters = sqliteTable("chapters", {
  id: text("id").primaryKey(),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  county: text("county").notNull(),
  state: text("state").notNull(),
  status: text("status").notNull().default("in_development"),
  description: text("description").notNull().default(""),
  contactEmail: text("contact_email"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const memberProfiles = sqliteTable(
  "member_profiles",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    legalFirstName: text("legal_first_name").notNull(),
    legalLastName: text("legal_last_name").notNull(),
    preferredName: text("preferred_name"),
    phoneEncrypted: text("phone_encrypted"),
    city: text("city"),
    state: text("state"),
    postalCode: text("postal_code"),
    chapterId: text("chapter_id").references(() => chapters.id),
    joinedAt: integer("joined_at", { mode: "timestamp_ms" }),
    status: text("status").notNull().default("pending"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    uniqueIndex("member_profiles_user_id_idx").on(table.userId),
    index("member_profiles_chapter_id_idx").on(table.chapterId),
  ],
);

export const membershipApplications = sqliteTable(
  "membership_applications",
  {
    id: text("id").primaryKey(),
    applicationNumber: text("application_number").notNull().unique(),
    legalName: text("legal_name").notNull(),
    preferredName: text("preferred_name"),
    email: text("email").notNull(),
    phoneEncrypted: text("phone_encrypted"),
    city: text("city"),
    state: text("state"),
    postalCode: text("postal_code"),
    desiredChapterId: text("desired_chapter_id").references(() => chapters.id),
    interestsJson: text("interests_json").notNull().default("[]"),
    skillsJson: text("skills_json").notNull().default("[]"),
    volunteerInterestsJson: text("volunteer_interests_json")
      .notNull()
      .default("[]"),
    programInterestsJson: text("program_interests_json")
      .notNull()
      .default("[]"),
    policiesAcceptedAt: integer("policies_accepted_at", {
      mode: "timestamp_ms",
    }),
    privacyAcknowledgedAt: integer("privacy_acknowledged_at", {
      mode: "timestamp_ms",
    }),
    status: text("status").notNull().default("submitted"),
    submittedAt: integer("submitted_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    reviewedAt: integer("reviewed_at", { mode: "timestamp_ms" }),
    reviewedBy: text("reviewed_by").references(() => user.id),
    decisionNotesEncrypted: text("decision_notes_encrypted"),
    notificationStatus: text("notification_status").notNull().default("pending"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("membership_applications_status_idx").on(
      table.status,
      table.submittedAt,
    ),
    index("membership_applications_email_idx").on(table.email),
    index("membership_applications_chapter_idx").on(table.desiredChapterId),
  ],
);

export const applicationReviews = sqliteTable(
  "application_reviews",
  {
    id: text("id").primaryKey(),
    applicationId: text("application_id")
      .notNull()
      .references(() => membershipApplications.id, { onDelete: "cascade" }),
    reviewerId: text("reviewer_id")
      .notNull()
      .references(() => user.id),
    action: text("action").notNull(),
    notesEncrypted: text("notes_encrypted"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    index("application_reviews_application_idx").on(
      table.applicationId,
      table.createdAt,
    ),
  ],
);

export const memberships = sqliteTable(
  "memberships",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    chapterId: text("chapter_id").references(() => chapters.id),
    memberNumber: text("member_number").notNull().unique(),
    status: text("status").notNull().default("pending_activation"),
    joinedAt: integer("joined_at", { mode: "timestamp_ms" }),
    activatedAt: integer("activated_at", { mode: "timestamp_ms" }),
    endsAt: integer("ends_at", { mode: "timestamp_ms" }),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("memberships_user_id_idx").on(table.userId),
    index("memberships_chapter_status_idx").on(table.chapterId, table.status),
  ],
);

export const membershipStatusHistory = sqliteTable(
  "membership_status_history",
  {
    id: text("id").primaryKey(),
    membershipId: text("membership_id")
      .notNull()
      .references(() => memberships.id, { onDelete: "cascade" }),
    fromStatus: text("from_status"),
    toStatus: text("to_status").notNull(),
    reason: text("reason"),
    actorId: text("actor_id").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    index("membership_status_history_membership_idx").on(
      table.membershipId,
      table.createdAt,
    ),
  ],
);

export const membershipSubscriptions = sqliteTable(
  "membership_subscriptions",
  {
    id: text("id").primaryKey(),
    membershipId: text("membership_id")
      .notNull()
      .references(() => memberships.id, { onDelete: "cascade" }),
    stripeCustomerId: text("stripe_customer_id"),
    stripeSubscriptionId: text("stripe_subscription_id").unique(),
    priceId: text("price_id"),
    status: text("status").notNull().default("not_configured"),
    currentPeriodStart: integer("current_period_start", {
      mode: "timestamp_ms",
    }),
    currentPeriodEnd: integer("current_period_end", { mode: "timestamp_ms" }),
    cancelAtPeriodEnd: integer("cancel_at_period_end", { mode: "boolean" })
      .default(false)
      .notNull(),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("membership_subscriptions_membership_idx").on(table.membershipId),
  ],
);

export const paymentEvents = sqliteTable(
  "payment_events",
  {
    id: text("id").primaryKey(),
    stripeEventId: text("stripe_event_id").notNull().unique(),
    type: text("type").notNull(),
    stripeCustomerId: text("stripe_customer_id"),
    stripeSubscriptionId: text("stripe_subscription_id"),
    amountCents: integer("amount_cents"),
    currency: text("currency"),
    status: text("status").notNull().default("received"),
    occurredAt: integer("occurred_at", { mode: "timestamp_ms" }),
    processedAt: integer("processed_at", { mode: "timestamp_ms" }),
    payloadSummaryJson: text("payload_summary_json").notNull().default("{}"),
  },
  (table) => [
    index("payment_events_subscription_idx").on(table.stripeSubscriptionId),
    index("payment_events_occurred_idx").on(table.occurredAt),
  ],
);

export const invitations = sqliteTable(
  "invitations",
  {
    id: text("id").primaryKey(),
    email: text("email").notNull(),
    tokenHash: text("token_hash").notNull().unique(),
    purpose: text("purpose").notNull().default("member_activation"),
    intendedRole: text("intended_role").notNull().default("member"),
    applicationId: text("application_id").references(
      () => membershipApplications.id,
    ),
    expiresAt: integer("expires_at", { mode: "timestamp_ms" }).notNull(),
    consumedAt: integer("consumed_at", { mode: "timestamp_ms" }),
    revokedAt: integer("revoked_at", { mode: "timestamp_ms" }),
    createdBy: text("created_by").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    deliveryStatus: text("delivery_status").notNull().default("not_configured"),
    deliveryError: text("delivery_error"),
  },
  (table) => [
    index("invitations_email_idx").on(table.email),
    index("invitations_expires_idx").on(table.expiresAt),
  ],
);

export const roleAssignments = sqliteTable(
  "role_assignments",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    roleKey: text("role_key").notNull(),
    scopeType: text("scope_type").notNull().default("global"),
    scopeId: text("scope_id"),
    grantedBy: text("granted_by").references(() => user.id),
    grantedAt: integer("granted_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    revokedAt: integer("revoked_at", { mode: "timestamp_ms" }),
    revokedBy: text("revoked_by").references(() => user.id),
  },
  (table) => [
    index("role_assignments_user_idx").on(table.userId, table.revokedAt),
    index("role_assignments_scope_idx").on(
      table.scopeType,
      table.scopeId,
      table.revokedAt,
    ),
  ],
);

export const adminAuditEvents = sqliteTable(
  "admin_audit_events",
  {
    id: text("id").primaryKey(),
    actorUserId: text("actor_user_id").references(() => user.id),
    action: text("action").notNull(),
    targetType: text("target_type").notNull(),
    targetId: text("target_id"),
    outcome: text("outcome").notNull(),
    requestId: text("request_id"),
    ipHash: text("ip_hash"),
    userAgent: text("user_agent"),
    metadataJson: text("metadata_json").notNull().default("{}"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    index("admin_audit_events_created_idx").on(table.createdAt),
    index("admin_audit_events_actor_idx").on(table.actorUserId, table.createdAt),
    index("admin_audit_events_action_idx").on(table.action, table.createdAt),
  ],
);

export const directoryProfiles = sqliteTable(
  "directory_profiles",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    displayName: text("display_name").notNull(),
    chapterId: text("chapter_id").references(() => chapters.id),
    profession: text("profession"),
    businessName: text("business_name"),
    skillsJson: text("skills_json").notNull().default("[]"),
    expertiseJson: text("expertise_json").notNull().default("[]"),
    volunteerInterestsJson: text("volunteer_interests_json")
      .notNull()
      .default("[]"),
    visible: integer("visible", { mode: "boolean" }).default(false).notNull(),
    contactPreferencesJson: text("contact_preferences_json")
      .notNull()
      .default("{}"),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    uniqueIndex("directory_profiles_user_id_idx").on(table.userId),
    index("directory_profiles_chapter_visible_idx").on(
      table.chapterId,
      table.visible,
    ),
  ],
);

export const contactMessages = sqliteTable(
  "contact_messages",
  {
    id: text("id").primaryKey(),
    name: text("name").notNull(),
    email: text("email").notNull(),
    subject: text("subject").notNull(),
    message: text("message").notNull(),
    status: text("status").notNull().default("new"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [index("contact_messages_created_idx").on(table.createdAt)],
);
