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

console.log(
  `Migration verification passed: ${expectedTables.length} tables, 2 audit triggers, Pasco chapter seeded.`,
);
