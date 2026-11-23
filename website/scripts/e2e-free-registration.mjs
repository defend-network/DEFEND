import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import path from "node:path";
import * as OTPAuth from "otpauth";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8787";
const edgePath =
  process.env.E2E_BROWSER_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

const suffix = Date.now().toString(36);
const email = `free.e2e.${suffix}@example.com`;
const password = `FreeE2E-${suffix}-Password-2026!`;

const remote = process.env.E2E_D1_MODE === "remote";

function query(sql) {
  const wrangler = path.resolve("node_modules/wrangler/bin/wrangler.js");
  const args = [wrangler, "d1", "execute", "DB"];
  if (remote) args.push("--remote", "--env", "staging");
  else args.push("--local");
  args.push("--json", "--command", sql);
  const output = execFileSync(process.execPath, args, { encoding: "utf8" });
  return JSON.parse(output)[0]?.results ?? [];
}

const browser = await chromium.launch({ executablePath: edgePath, headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${baseURL}/register`, { waitUntil: "load" });
  await page.locator("#register-name").fill("Free E2E Member");
  await page.locator("#register-email").fill(email);
  await page.locator("#register-password").fill(password);
  await page.locator('input[name="adultConfirmed"]').check();
  await page.waitForFunction(
    () => {
      const input = document.querySelector(
        'input[name="cf-turnstile-response"]',
      );
      return Boolean(input && input.value.length > 0);
    },
    { timeout: 30_000 },
  );
  await page.getByRole("button", { name: "Create free account" }).click();
  try {
    await page
      .getByText("Registration received", { exact: false })
      .waitFor({ timeout: 30_000 });
  } catch (error) {
    const alerts = await page.locator('[role="alert"]').allInnerTexts();
    console.error("FORM_ALERTS:", JSON.stringify(alerts));
    throw error;
  }
  console.log("PASS free registration form");

  const escaped = email.replaceAll("'", "''");
  const rows = query(
    `SELECT u.id AS user_id, u.email, u.email_verified, m.status, m.member_number, t.key AS tier_key
     FROM user u
     JOIN memberships m ON m.user_id = u.id
     LEFT JOIN membership_tiers t ON t.id = m.tier_id
     WHERE u.email = '${escaped}';`,
  );
  const row = rows[0];
  if (!row) throw new Error("Free user or membership was not persisted.");
  if (row.status !== "free_access") {
    throw new Error(`Unexpected membership status: ${row.status}`);
  }
  if (row.tier_key !== "free") {
    throw new Error(`Unexpected tier: ${row.tier_key}`);
  }
  if (Number(row.email_verified) !== 0) {
    throw new Error("Free registration should not mark the email verified.");
  }
  console.log(`PASS free membership persisted (${row.member_number})`);

  const outbox = query(
    `SELECT subject, text_body, html_body FROM email_outbox WHERE recipient = '${escaped}' ORDER BY created_at DESC LIMIT 1;`,
  );
  if (!outbox[0]?.subject) {
    throw new Error("Verification email was not written to the outbox.");
  }
  console.log("PASS verification email queued");

  const body = outbox[0].text_body ?? "";
  const match = body.match(/https?:\/\/[^\s"'<>]+verify-email[^\s"'<>]*/);
  if (!match) {
    throw new Error("Verification URL was not found in the outbox message.");
  }
  await page.goto(match[0], { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  console.log("PASS email verification link accepted");

  await page.goto(`${baseURL}/login`, { waitUntil: "load" });
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/members/, { timeout: 30_000 });
  const memberBody = await page.locator("body").innerText();
  if (!memberBody.toLowerCase().includes("free access")) {
    throw new Error("Member dashboard did not show the free access standing.");
  }
  console.log("PASS free account sign-in after verification");

  const gates = [
    ["/members/directory", "Standard membership required"],
    ["/members/volunteers", "Standard membership required"],
    ["/members/card", "Paid membership required"],
  ];
  for (const [pathName, expected] of gates) {
    await page.goto(`${baseURL}${pathName}`, { waitUntil: "domcontentloaded" });
    const text = await page.locator("body").innerText();
    if (!text.includes(expected)) {
      throw new Error(`Free account gate failed for ${pathName}`);
    }
  }
  console.log("PASS free account paid-feature gates");

  await page.context().clearCookies();
  await page.goto(`${baseURL}/login/email-code`, { waitUntil: "load" });
  await page.locator("#email-code-email").fill(email);
  await page.getByRole("button", { name: "Send sign-in code" }).click();
  await page.locator("#email-code").waitFor({ timeout: 30_000 });
  const otpRows = query(
    `SELECT text_body FROM email_outbox WHERE recipient='${escaped}' AND subject='DEFEND verification code' ORDER BY created_at DESC LIMIT 1;`,
  );
  const otpMatch = (otpRows[0]?.text_body ?? "").match(/\b(\d{6})\b/);
  if (!otpMatch) throw new Error("Email sign-in code was not found in the outbox.");
  await page.locator("#email-code").fill(otpMatch[1]);
  await page.getByRole("button", { name: "Verify and continue" }).click();
  await page.waitForURL(/\/members/, { timeout: 30_000 });
  console.log("PASS email OTP sign-in");

  await page.goto(`${baseURL}/members/account/security`, {
    waitUntil: "domcontentloaded",
  });
  await page.locator("#enable-password").fill(password);
  const enableResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/auth/two-factor/enable") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Set up authenticator app" }).click();
  const enableResponse = await enableResponsePromise;
  const enablePayload = await enableResponse.json();
  const totpURI = enablePayload.totpURI ?? enablePayload.data?.totpURI;
  if (!totpURI) {
    console.error("ENABLE_STATUS", enableResponse.status());
    console.error("ENABLE_KEYS", Object.keys(enablePayload));
    throw new Error("Authenticator enrollment did not return a TOTP URI.");
  }
  if ((await page.locator("pre").count()) > 0) {
    throw new Error("Recovery codes were displayed before authenticator verification.");
  }
  const totp = OTPAuth.URI.parse(totpURI);
  await page.locator("#totp-code").fill(totp.generate());
  await page.getByRole("button", { name: "Verify and enable authenticator" }).click();
  await page
    .getByText("Recovery codes — save these now", { exact: false })
    .waitFor({ timeout: 30_000 });
  const codeText = await page.locator("pre").last().innerText();
  const backupCodes = codeText
    .split("\n")
    .map((value) => value.trim())
    .filter(Boolean);
  if (backupCodes.length === 0) {
    throw new Error("No recovery codes were displayed after verification.");
  }
  const markerRows = query(
    `SELECT COUNT(*) AS verified FROM session WHERE user_id='${row.user_id}' AND mfa_verified_at IS NOT NULL;`,
  );
  if (!markerRows[0]?.verified) {
    throw new Error("The session was not marked as MFA-verified.");
  }
  console.log("PASS authenticator enrollment and session MFA marker");
  await page.getByRole("button", { name: "I have saved these codes" }).click();
  await page.context().clearCookies();
  await page.goto(`${baseURL}/login`, { waitUntil: "load" });
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/login\/two-factor/, { timeout: 30_000 });
  await page.getByRole("button", { name: "Use a backup code instead" }).click();
  await page.locator("#code").fill(backupCodes[0]);
  await page.getByRole("button", { name: "Verify and continue" }).click();
  await page.waitForURL(/\/members/, { timeout: 30_000 });
  const backupMarkerRows = query(
    `SELECT COUNT(*) AS verified FROM session WHERE user_id='${row.user_id}' AND mfa_verified_at IS NOT NULL;`,
  );
  if (!backupMarkerRows[0]?.verified) {
    throw new Error("The backup-code session was not marked as MFA-verified.");
  }
  console.log("PASS backup-code sign-in and MFA marker");
} finally {
  await browser.close();
}
