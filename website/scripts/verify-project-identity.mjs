import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

const failures = [];
const warnings = [];
const requireIdentity = process.env.REQUIRE_DEFEND_IDENTITY === "true";

function git(args) {
  return execFileSync("git", ["-C", repoRoot, ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function check(condition, message) {
  if (!condition) failures.push(message);
}

let remote = "";
let branch = "";
try {
  remote = git(["remote", "get-url", "origin"]);
  branch = git(["branch", "--show-current"]);
} catch (error) {
  failures.push(`Unable to inspect the repository: ${error.message}`);
}

if (remote) {
  check(
    remote.includes("defend-network/DEFEND"),
    `Unexpected origin remote: ${remote}`,
  );
}

if (branch) {
  check(
    branch === "rebuild/website-platform-v1" ||
      branch === "main" ||
      branch.startsWith("agent/") ||
      branch.startsWith("rebuild/"),
    `Unexpected branch for a DEFEND operation: ${branch}`,
  );
}

const expectedGithubAccount = process.env.DEFEND_GITHUB_ACCOUNT?.trim();
if (expectedGithubAccount) {
  try {
    const account = execFileSync(
      "gh",
      ["api", "user", "--jq", ".login"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    ).trim();
    check(
      account === expectedGithubAccount,
      `GitHub CLI is authenticated as ${account}; expected ${expectedGithubAccount}.`,
    );
  } catch {
    warnings.push(
      "GitHub CLI account could not be verified; set GH_CONFIG_DIR or authenticate gh.",
    );
  }
} else {
  const message =
    "DEFEND_GITHUB_ACCOUNT is not set; GitHub identity was not verified.";
  if (requireIdentity) failures.push(message);
  else warnings.push(message);
}

const expectedCloudflareAccount = process.env.DEFEND_CLOUDFLARE_ACCOUNT_ID?.trim();
const cloudflareAccount = process.env.CLOUDFLARE_ACCOUNT_ID?.trim();
if (expectedCloudflareAccount) {
  if (!cloudflareAccount) {
    warnings.push(
      "CLOUDFLARE_ACCOUNT_ID is not set; Cloudflare target was not verified.",
    );
  } else {
    check(
      cloudflareAccount === expectedCloudflareAccount,
      `Cloudflare account ${cloudflareAccount} does not match the approved DEFEND account.`,
    );
  }
} else {
  const message =
    "DEFEND_CLOUDFLARE_ACCOUNT_ID is not set; Cloudflare target was not verified.";
  if (requireIdentity) failures.push(message);
  else warnings.push(message);
}

const stripeKey = process.env.STRIPE_SECRET_KEY?.trim();
if (stripeKey) {
  const liveMode = process.env.PAYMENTS_MODE === "live";
  if (liveMode) {
    check(
      stripeKey.startsWith("sk_live_"),
      "PAYMENTS_MODE=live requires a live Stripe secret key.",
    );
    check(
      process.env.PAYMENTS_LIVE_APPROVED === "true",
      "Live payments require PAYMENTS_LIVE_APPROVED=true.",
    );
  } else {
    check(
      stripeKey.startsWith("sk_test_"),
      "Test mode requires a Stripe test secret key.",
    );
  }
}

for (const warning of warnings) console.warn(`WARN ${warning}`);
for (const failure of failures) console.error(`FAIL ${failure}`);

if (failures.length) {
  console.error("Project identity verification failed.");
  process.exit(1);
}

console.log(
  `Project identity verified: ${branch || "detached HEAD"} at ${remote || "unknown remote"}.`,
);
