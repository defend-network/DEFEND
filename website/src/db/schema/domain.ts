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
    notificationPreferencesJson: text("notification_preferences_json")
      .notNull()
      .default("{}"),
    familyParticipation: integer("family_participation", { mode: "boolean" })
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
    recommendedChapterId: text("recommended_chapter_id").references(
      () => chapters.id,
    ),
    referralSource: text("referral_source"),
    referrerUrl: text("referrer_url"),
    utmSource: text("utm_source"),
    utmMedium: text("utm_medium"),
    utmCampaign: text("utm_campaign"),
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
    infoRequestEncrypted: text("info_request_encrypted"),
    infoRequestedAt: integer("info_requested_at", { mode: "timestamp_ms" }),
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
    applicationId: text("application_id")
      .unique()
      .references(() => membershipApplications.id),
    chapterId: text("chapter_id").references(() => chapters.id),
    memberNumber: text("member_number").notNull().unique(),
    status: text("status").notNull().default("pending_activation"),
    duesStatus: text("dues_status").notNull().default("not_started"),
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
    uniqueIndex("memberships_user_id_unique").on(table.userId),
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

export const applicationUpdateTokens = sqliteTable(
  "application_update_tokens",
  {
    id: text("id").primaryKey(),
    applicationId: text("application_id")
      .notNull()
      .references(() => membershipApplications.id, { onDelete: "cascade" }),
    tokenHash: text("token_hash").notNull().unique(),
    expiresAt: integer("expires_at", { mode: "timestamp_ms" }).notNull(),
    consumedAt: integer("consumed_at", { mode: "timestamp_ms" }),
    createdBy: text("created_by").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    index("application_update_tokens_application_idx").on(
      table.applicationId,
      table.createdAt,
    ),
  ],
);

export const emailOutbox = sqliteTable(
  "email_outbox",
  {
    id: text("id").primaryKey(),
    recipient: text("recipient").notNull(),
    subject: text("subject").notNull(),
    textBody: text("text_body").notNull(),
    htmlBody: text("html_body"),
    templateKey: text("template_key").notNull(),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [index("email_outbox_created_idx").on(table.createdAt)],
);

export const emailDeliveryEvents = sqliteTable(
  "email_delivery_events",
  {
    id: text("id").primaryKey(),
    recipient: text("recipient").notNull(),
    templateKey: text("template_key").notNull(),
    provider: text("provider").notNull(),
    providerMessageId: text("provider_message_id"),
    status: text("status").notNull(),
    errorCode: text("error_code"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    index("email_delivery_events_created_idx").on(table.createdAt),
    index("email_delivery_events_recipient_idx").on(table.recipient),
  ],
);

export const requestRateLimits = sqliteTable("request_rate_limits", {
  key: text("key").primaryKey(),
  count: integer("count").notNull(),
  windowStart: integer("window_start").notNull(),
  expiresAt: integer("expires_at").notNull(),
});

export const events = sqliteTable(
  "events",
  {
    id: text("id").primaryKey(),
    slug: text("slug").notNull().unique(),
    title: text("title").notNull(),
    summary: text("summary").notNull().default(""),
    description: text("description").notNull().default(""),
    programId: text("program_id"),
    chapterId: text("chapter_id").references(() => chapters.id),
    startsAt: integer("starts_at", { mode: "timestamp_ms" }).notNull(),
    endsAt: integer("ends_at", { mode: "timestamp_ms" }),
    locationName: text("location_name"),
    address: text("address"),
    capacity: integer("capacity"),
    feeCents: integer("fee_cents").default(0).notNull(),
    familyFriendly: integer("family_friendly", { mode: "boolean" })
      .default(false)
      .notNull(),
    youthSafeguardingRequired: integer("youth_safeguarding_required", {
      mode: "boolean",
    })
      .default(false)
      .notNull(),
    status: text("status").notNull().default("draft"),
    registrationOpensAt: integer("registration_opens_at", {
      mode: "timestamp_ms",
    }),
    registrationClosesAt: integer("registration_closes_at", {
      mode: "timestamp_ms",
    }),
    createdBy: text("created_by").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("events_chapter_status_idx").on(table.chapterId, table.status),
    index("events_starts_at_idx").on(table.startsAt),
  ],
);

export const eventRegistrations = sqliteTable(
  "event_registrations",
  {
    id: text("id").primaryKey(),
    eventId: text("event_id")
      .notNull()
      .references(() => events.id, { onDelete: "cascade" }),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    status: text("status").notNull().default("registered"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    uniqueIndex("event_registrations_event_user_idx").on(
      table.eventId,
      table.userId,
    ),
    index("event_registrations_event_status_idx").on(
      table.eventId,
      table.status,
    ),
  ],
);

export const eventCheckins = sqliteTable(
  "event_checkins",
  {
    id: text("id").primaryKey(),
    eventId: text("event_id")
      .notNull()
      .references(() => events.id, { onDelete: "cascade" }),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    checkedInAt: integer("checked_in_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    checkedInBy: text("checked_in_by").references(() => user.id),
    method: text("method").notNull().default("qr"),
  },
  (table) => [
    uniqueIndex("event_checkins_event_user_idx").on(
      table.eventId,
      table.userId,
    ),
  ],
);

export const volunteerOpportunities = sqliteTable(
  "volunteer_opportunities",
  {
    id: text("id").primaryKey(),
    chapterId: text("chapter_id").references(() => chapters.id),
    eventId: text("event_id").references(() => events.id),
    title: text("title").notNull(),
    description: text("description").notNull().default(""),
    slots: integer("slots"),
    skillsJson: text("skills_json").notNull().default("[]"),
    availability: text("availability"),
    isInstructorRole: integer("is_instructor_role", { mode: "boolean" })
      .default(false)
      .notNull(),
    status: text("status").notNull().default("draft"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("volunteer_opportunities_chapter_status_idx").on(
      table.chapterId,
      table.status,
    ),
  ],
);

export const volunteerRegistrations = sqliteTable(
  "volunteer_registrations",
  {
    id: text("id").primaryKey(),
    opportunityId: text("opportunity_id")
      .notNull()
      .references(() => volunteerOpportunities.id, { onDelete: "cascade" }),
    userId: text("user_id")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    status: text("status").notNull().default("registered"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    uniqueIndex("volunteer_registrations_opportunity_user_idx").on(
      table.opportunityId,
      table.userId,
    ),
  ],
);

export const organizations = sqliteTable(
  "organizations",
  {
    id: text("id").primaryKey(),
    name: text("name").notNull(),
    type: text("type").notNull().default("other"),
    website: text("website"),
    email: text("email"),
    phoneEncrypted: text("phone_encrypted"),
    address: text("address"),
    city: text("city"),
    state: text("state"),
    postalCode: text("postal_code"),
    status: text("status").notNull().default("active"),
    notesEncrypted: text("notes_encrypted"),
    createdBy: text("created_by").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("organizations_name_idx").on(table.name),
    index("organizations_type_status_idx").on(table.type, table.status),
  ],
);

export const contacts = sqliteTable(
  "contacts",
  {
    id: text("id").primaryKey(),
    organizationId: text("organization_id").references(() => organizations.id),
    firstName: text("first_name").notNull(),
    lastName: text("last_name").notNull(),
    title: text("title"),
    email: text("email"),
    phoneEncrypted: text("phone_encrypted"),
    tagsJson: text("tags_json").notNull().default("[]"),
    notesEncrypted: text("notes_encrypted"),
    status: text("status").notNull().default("active"),
    ownerUserId: text("owner_user_id").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("contacts_organization_idx").on(table.organizationId),
    index("contacts_name_idx").on(table.lastName, table.firstName),
  ],
);

export const crmLeads = sqliteTable(
  "crm_leads",
  {
    id: text("id").primaryKey(),
    organizationId: text("organization_id").references(() => organizations.id),
    contactId: text("contact_id").references(() => contacts.id),
    type: text("type").notNull().default("other"),
    title: text("title").notNull(),
    source: text("source"),
    stage: text("stage").notNull().default("new"),
    priority: text("priority").notNull().default("normal"),
    assignedTo: text("assigned_to").references(() => user.id),
    nextFollowUpAt: integer("next_follow_up_at", { mode: "timestamp_ms" }),
    notesEncrypted: text("notes_encrypted"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [
    index("crm_leads_stage_idx").on(table.stage, table.nextFollowUpAt),
    index("crm_leads_type_idx").on(table.type),
  ],
);

export const crmActivities = sqliteTable(
  "crm_activities",
  {
    id: text("id").primaryKey(),
    leadId: text("lead_id").references(() => crmLeads.id, {
      onDelete: "cascade",
    }),
    contactId: text("contact_id").references(() => contacts.id, {
      onDelete: "cascade",
    }),
    type: text("type").notNull().default("note"),
    summary: text("summary").notNull(),
    occurredAt: integer("occurred_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    createdBy: text("created_by").references(() => user.id),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
  },
  (table) => [
    index("crm_activities_lead_idx").on(table.leadId, table.occurredAt),
  ],
);

export const crmTasks = sqliteTable(
  "crm_tasks",
  {
    id: text("id").primaryKey(),
    leadId: text("lead_id").references(() => crmLeads.id, {
      onDelete: "cascade",
    }),
    title: text("title").notNull(),
    dueAt: integer("due_at", { mode: "timestamp_ms" }),
    assignedTo: text("assigned_to").references(() => user.id),
    status: text("status").notNull().default("open"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    completedAt: integer("completed_at", { mode: "timestamp_ms" }),
  },
  (table) => [index("crm_tasks_status_due_idx").on(table.status, table.dueAt)],
);

export const crmAttachments = sqliteTable("crm_attachments", {
  id: text("id").primaryKey(),
  leadId: text("lead_id").references(() => crmLeads.id, { onDelete: "cascade" }),
  documentId: text("document_id"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const propertyLeads = sqliteTable(
  "property_leads",
  {
    id: text("id").primaryKey(),
    organizationId: text("organization_id").references(() => organizations.id),
    contactId: text("contact_id").references(() => contacts.id),
    address: text("address").notNull(),
    city: text("city"),
    state: text("state"),
    postalCode: text("postal_code"),
    buildingSqft: integer("building_sqft"),
    acreage: text("acreage"),
    ownerName: text("owner_name"),
    listingUrl: text("listing_url"),
    leaseOrDonation: text("lease_or_donation").notNull().default("unknown"),
    status: text("status").notNull().default("new"),
    estimatedCostCents: integer("estimated_cost_cents"),
    notesEncrypted: text("notes_encrypted"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [index("property_leads_status_idx").on(table.status)],
);

export const facilityProjects = sqliteTable(
  "facility_projects",
  {
    id: text("id").primaryKey(),
    propertyLeadId: text("property_lead_id").references(() => propertyLeads.id),
    name: text("name").notNull(),
    stage: text("stage").notNull().default("concept"),
    budgetCents: integer("budget_cents"),
    targetDate: integer("target_date", { mode: "timestamp_ms" }),
    status: text("status").notNull().default("active"),
    notesEncrypted: text("notes_encrypted"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [index("facility_projects_status_idx").on(table.status)],
);

export const partnershipProposals = sqliteTable("partnership_proposals", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").references(() => organizations.id),
  contactId: text("contact_id").references(() => contacts.id),
  type: text("type").notNull().default("other"),
  title: text("title").notNull(),
  description: text("description").notNull().default(""),
  amountCents: integer("amount_cents"),
  status: text("status").notNull().default("draft"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const programs = sqliteTable("programs", {
  id: text("id").primaryKey(),
  slug: text("slug").notNull().unique(),
  title: text("title").notNull(),
  summary: text("summary").notNull().default(""),
  description: text("description").notNull().default(""),
  chapterId: text("chapter_id").references(() => chapters.id),
  status: text("status").notNull().default("planned"),
  capacity: integer("capacity"),
  feeCents: integer("fee_cents").default(0).notNull(),
  eligibility: text("eligibility"),
  familyFriendly: integer("family_friendly", { mode: "boolean" })
    .default(false)
    .notNull(),
  youthSafeguardingRequired: integer("youth_safeguarding_required", {
    mode: "boolean",
  })
    .default(false)
    .notNull(),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const documents = sqliteTable(
  "documents",
  {
    id: text("id").primaryKey(),
    title: text("title").notNull(),
    description: text("description").notNull().default(""),
    category: text("category").notNull().default("general"),
    r2Key: text("r2_key").notNull(),
    filename: text("filename").notNull(),
    mimeType: text("mime_type").notNull(),
    sizeBytes: integer("size_bytes").notNull(),
    version: integer("version").notNull().default(1),
    visibility: text("visibility").notNull().default("admin"),
    chapterId: text("chapter_id").references(() => chapters.id),
    ownerUserId: text("owner_user_id").references(() => user.id),
    status: text("status").notNull().default("draft"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
    deletedAt: integer("deleted_at", { mode: "timestamp_ms" }),
  },
  (table) => [
    index("documents_visibility_status_idx").on(table.visibility, table.status),
    index("documents_category_idx").on(table.category),
  ],
);

export const documentVersions = sqliteTable("document_versions", {
  id: text("id").primaryKey(),
  documentId: text("document_id")
    .notNull()
    .references(() => documents.id, { onDelete: "cascade" }),
  version: integer("version").notNull(),
  r2Key: text("r2_key").notNull(),
  filename: text("filename").notNull(),
  sizeBytes: integer("size_bytes").notNull(),
  uploadedBy: text("uploaded_by").references(() => user.id),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const documentPermissions = sqliteTable("document_permissions", {
  id: text("id").primaryKey(),
  documentId: text("document_id")
    .notNull()
    .references(() => documents.id, { onDelete: "cascade" }),
  roleKey: text("role_key").notNull(),
  scopeType: text("scope_type").notNull().default("global"),
  scopeId: text("scope_id"),
  permission: text("permission").notNull().default("view"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const mediaAssets = sqliteTable("media_assets", {
  id: text("id").primaryKey(),
  r2Key: text("r2_key").notNull(),
  filename: text("filename").notNull(),
  mimeType: text("mime_type").notNull(),
  sizeBytes: integer("size_bytes").notNull(),
  width: integer("width"),
  height: integer("height"),
  altText: text("alt_text"),
  credit: text("credit"),
  license: text("license"),
  sourceUrl: text("source_url"),
  visibility: text("visibility").notNull().default("public"),
  uploadedBy: text("uploaded_by").references(() => user.id),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const cmsPages = sqliteTable("cms_pages", {
  id: text("id").primaryKey(),
  slug: text("slug").notNull().unique(),
  title: text("title").notNull(),
  seoTitle: text("seo_title"),
  seoDescription: text("seo_description"),
  status: text("status").notNull().default("draft"),
  publishedAt: integer("published_at", { mode: "timestamp_ms" }),
  updatedBy: text("updated_by").references(() => user.id),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const cmsPageBlocks = sqliteTable(
  "cms_page_blocks",
  {
    id: text("id").primaryKey(),
    pageId: text("page_id")
      .notNull()
      .references(() => cmsPages.id, { onDelete: "cascade" }),
    blockType: text("block_type").notNull(),
    sortOrder: integer("sort_order").notNull().default(0),
    contentJson: text("content_json").notNull().default("{}"),
    createdAt: integer("created_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp_ms" })
      .default(timestampDefault)
      .$onUpdate(() => new Date())
      .notNull(),
  },
  (table) => [index("cms_page_blocks_page_idx").on(table.pageId, table.sortOrder)],
);

export const cmsArticles = sqliteTable("cms_articles", {
  id: text("id").primaryKey(),
  slug: text("slug").notNull().unique(),
  title: text("title").notNull(),
  excerpt: text("excerpt").notNull().default(""),
  contentJson: text("content_json").notNull().default("{}"),
  category: text("category").notNull().default("news"),
  status: text("status").notNull().default("draft"),
  seoTitle: text("seo_title"),
  seoDescription: text("seo_description"),
  publishedAt: integer("published_at", { mode: "timestamp_ms" }),
  authorId: text("author_id").references(() => user.id),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const cmsRevisions = sqliteTable("cms_revisions", {
  id: text("id").primaryKey(),
  entityType: text("entity_type").notNull(),
  entityId: text("entity_id").notNull(),
  snapshotJson: text("snapshot_json").notNull(),
  createdBy: text("created_by").references(() => user.id),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const announcements = sqliteTable("announcements", {
  id: text("id").primaryKey(),
  title: text("title").notNull(),
  body: text("body").notNull(),
  visibility: text("visibility").notNull().default("members"),
  startsAt: integer("starts_at", { mode: "timestamp_ms" }),
  endsAt: integer("ends_at", { mode: "timestamp_ms" }),
  publishedAt: integer("published_at", { mode: "timestamp_ms" }),
  createdBy: text("created_by").references(() => user.id),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const donations = sqliteTable("donations", {
  id: text("id").primaryKey(),
  donorContactId: text("donor_contact_id").references(() => contacts.id),
  membershipId: text("membership_id").references(() => memberships.id),
  amountCents: integer("amount_cents").notNull(),
  currency: text("currency").notNull().default("usd"),
  method: text("method").notNull().default("manual"),
  stripePaymentId: text("stripe_payment_id"),
  status: text("status").notNull().default("recorded"),
  receivedAt: integer("received_at", { mode: "timestamp_ms" }),
  receiptStatus: text("receipt_status").notNull().default("not_issued"),
  notesEncrypted: text("notes_encrypted"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const pledges = sqliteTable("pledges", {
  id: text("id").primaryKey(),
  donorContactId: text("donor_contact_id").references(() => contacts.id),
  amountCents: integer("amount_cents").notNull(),
  frequency: text("frequency").notNull().default("one_time"),
  status: text("status").notNull().default("open"),
  dueAt: integer("due_at", { mode: "timestamp_ms" }),
  fulfilledAmountCents: integer("fulfilled_amount_cents").default(0).notNull(),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const expenses = sqliteTable("expenses", {
  id: text("id").primaryKey(),
  chapterId: text("chapter_id").references(() => chapters.id),
  category: text("category").notNull(),
  vendor: text("vendor").notNull(),
  amountCents: integer("amount_cents").notNull(),
  incurredAt: integer("incurred_at", { mode: "timestamp_ms" }).notNull(),
  paidBy: text("paid_by"),
  receiptDocumentId: text("receipt_document_id").references(() => documents.id),
  status: text("status").notNull().default("recorded"),
  notesEncrypted: text("notes_encrypted"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const chapterAllocations = sqliteTable("chapter_allocations", {
  id: text("id").primaryKey(),
  chapterId: text("chapter_id")
    .notNull()
    .references(() => chapters.id),
  sourceType: text("source_type").notNull(),
  sourceId: text("source_id"),
  amountCents: integer("amount_cents").notNull(),
  period: text("period"),
  notes: text("notes"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const sponsorContributions = sqliteTable("sponsor_contributions", {
  id: text("id").primaryKey(),
  organizationId: text("organization_id").references(() => organizations.id),
  proposalId: text("proposal_id").references(() => partnershipProposals.id),
  amountCents: integer("amount_cents").notNull(),
  receivedAt: integer("received_at", { mode: "timestamp_ms" }),
  status: text("status").notNull().default("recorded"),
  notesEncrypted: text("notes_encrypted"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const integrationStatus = sqliteTable("integration_status", {
  id: text("id").primaryKey(),
  key: text("key").notNull().unique(),
  status: text("status").notNull().default("not_configured"),
  lastCheckedAt: integer("last_checked_at", { mode: "timestamp_ms" }),
  lastErrorCode: text("last_error_code"),
  metadataJson: text("metadata_json").notNull().default("{}"),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const systemJobs = sqliteTable("system_jobs", {
  id: text("id").primaryKey(),
  jobKey: text("job_key").notNull(),
  status: text("status").notNull().default("pending"),
  startedAt: integer("started_at", { mode: "timestamp_ms" }),
  finishedAt: integer("finished_at", { mode: "timestamp_ms" }),
  errorSummary: text("error_summary"),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
});

export const settings = sqliteTable("settings", {
  key: text("key").primaryKey(),
  valueJson: text("value_json").notNull().default("{}"),
  updatedBy: text("updated_by").references(() => user.id),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .$onUpdate(() => new Date())
    .notNull(),
});

export const newsletterSubscribers = sqliteTable("newsletter_subscribers", {
  id: text("id").primaryKey(),
  email: text("email").notNull().unique(),
  status: text("status").notNull().default("subscribed"),
  source: text("source"),
  consentAt: integer("consent_at", { mode: "timestamp_ms" }),
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .default(timestampDefault)
    .notNull(),
  unsubscribedAt: integer("unsubscribed_at", { mode: "timestamp_ms" }),
});
