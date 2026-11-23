import { execFileSync } from "node:child_process";
import path from "node:path";

const wranglerBin = path.resolve("node_modules/wrangler/bin/wrangler.js");

function wrangler(args) {
  return execFileSync(process.execPath, [wranglerBin, ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function query(sql) {
  const output = wrangler([
    "d1",
    "execute",
    "DB",
    "--local",
    "--json",
    "--command",
    sql,
  ]);
  const parsed = JSON.parse(output);
  return parsed[0]?.results ?? [];
}

wrangler(["d1", "migrations", "apply", "DB", "--local"]);

const expectedTables = [
  "user",
  "session",
  "account",
  "verification",
  "two_factor",
  "rate_limit",
  "chapters",
  "member_profiles",
  "membership_applications",
  "application_reviews",
  "memberships",
  "membership_status_history",
  "membership_subscriptions",
  "payment_events",
  "invitations",
  "role_assignments",
  "admin_audit_events",
  "directory_profiles",
  "contact_messages",
  "organizations",
  "contacts",
  "crm_leads",
  "crm_activities",
  "crm_tasks",
  "crm_attachments",
  "property_leads",
  "facility_projects",
  "partnership_proposals",
  "programs",
  "documents",
  "document_versions",
  "document_permissions",
  "media_assets",
  "cms_pages",
  "cms_page_blocks",
  "cms_articles",
  "cms_revisions",
  "announcements",
  "donations",
  "pledges",
  "expenses",
  "chapter_allocations",
  "sponsor_contributions",
  "integration_status",
  "system_jobs",
  "settings",  "application_update_tokens",
  "email_outbox",
  "email_delivery_events",
  "request_rate_limits",
  "events",
  "event_registrations",
  "event_checkins",
  "volunteer_opportunities",
  "volunteer_registrations",
  "newsletter_subscribers",
  "membership_tiers",
  "membership_tier_prices",
  "tier_entitlements",
  "member_entitlement_overrides",
  "households",
  "household_members",
  "feature_releases",
];

const tables = new Set(
  query("SELECT name FROM sqlite_master WHERE type='table'").map(
    (row) => row.name,
  ),
);
const missing = expectedTables.filter((table) => !tables.has(table));
if (missing.length) {
  throw new Error(`Missing tables: ${missing.join(", ")}`);
}

const triggers = new Set(
  query("SELECT name FROM sqlite_master WHERE type='trigger'").map(
    (row) => row.name,
  ),
);
for (const trigger of [
  "admin_audit_events_no_update",
  "admin_audit_events_no_delete",
]) {
  if (!triggers.has(trigger)) {
    throw new Error(`Missing audit trigger: ${trigger}`);
  }
}

const chapter = query(
  "SELECT id, slug, status FROM chapters WHERE id = 'chapter_pasco'",
);
if (chapter.length !== 1 || chapter[0].status !== "in_development") {
  throw new Error("Pasco chapter seed is missing or has the wrong status");
}

const tierKeys = new Set(
  query("SELECT key FROM membership_tiers").map((row) => row.key),
);
for (const tier of ["free", "standard", "supporter", "patron"]) {
  if (!tierKeys.has(tier)) {
    throw new Error(`Missing membership tier: ${tier}`);
  }
}

const releaseCount = query("SELECT count(*) AS value FROM feature_releases")[0]
  ?.value;
if (!releaseCount) {
  throw new Error("Feature release registry seed is missing");
}

const userColumns = new Set(
  query("PRAGMA table_info(user)").map((row) => row.name),
);
if (!userColumns.has("two_factor_enabled_at")) {
  throw new Error("Missing session-level MFA timestamp column");
}

const applicationColumns = new Set(
  query("PRAGMA table_info(membership_applications)").map((row) => row.name),
);
if (!applicationColumns.has("requested_tier_key")) {
  throw new Error("Missing application tier selection column");
}
if (!applicationColumns.has("adult_confirmed_at")) {
  throw new Error("Missing application adult confirmation column");
}

const sessionColumns = new Set(
  query("PRAGMA table_info(session)").map((row) => row.name),
);
if (!sessionColumns.has("mfa_verified_at")) {
  throw new Error("Missing session-level MFA verification column");
}

console.log(
  `Migration verification passed: ${expectedTables.length} tables, 2 audit triggers, Pasco chapter seeded, 4 tiers and release registry seeded.`,
);
