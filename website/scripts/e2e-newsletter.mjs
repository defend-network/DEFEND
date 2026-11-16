import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createHmac } from "node:crypto";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8787";
const edgePath = process.env.E2E_BROWSER_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const envFile = fs.existsSync(".dev.vars") ? fs.readFileSync(".dev.vars", "utf8") : "";
const envValue = (name) => {
  const match = envFile.match(new RegExp(`^${name}\\s*=\\s*["']?([^"'\r\n]+)`, "m"));
  return process.env[name] ?? match?.[1]?.trim();
};
const secret =
  envValue("NEWSLETTER_UNSUBSCRIBE_SECRET") ||
  envValue("CARD_TOKEN_SECRET") ||
  envValue("BETTER_AUTH_SECRET");
if (!secret) throw new Error("A local auth/card secret is required for the unsubscribe test.");

function base64Url(bytes) {
  return Buffer.from(bytes).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}
function tokenFor(id) {
  const payload = base64Url(Buffer.from(id));
  return `v1.${payload}.${base64Url(createHmac("sha256", secret).update(payload).digest())}`;
}
function query(sql) {
  const wrangler = path.resolve("node_modules/wrangler/bin/wrangler.js");
  const output = execFileSync(process.execPath, [wrangler, "d1", "execute", "DB", "--local", "--json", "--command", sql], { encoding: "utf8" });
  return JSON.parse(output)[0]?.results ?? [];
}

const email = `newsletter.unsubscribe.${Date.now().toString(36)}@example.com`;
const browser = await chromium.launch({ executablePath: edgePath, headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${baseURL}/newsletter`, { waitUntil: "load" });
  await page.waitForTimeout(1000);
  await page.locator("#newsletter-email").fill(email);
  await page.getByRole("checkbox", { name: /I consent/i }).check();
  await page.getByRole("button", { name: "Subscribe to updates" }).click();
  await page.getByText("You are subscribed", { exact: false }).waitFor({ timeout: 20000 });
  console.log("PASS newsletter subscription");

  const rows = query(`SELECT id FROM newsletter_subscribers WHERE email='${email.replaceAll("'", "''")}';`);
  if (!rows[0]?.id) throw new Error("Subscriber was not stored.");
  const token = tokenFor(rows[0].id);
  await page.goto(`${baseURL}/newsletter/unsubscribe?token=${encodeURIComponent(token)}`, { waitUntil: "load" });
  await page.waitForTimeout(800);
  const body = await page.locator("body").innerText();
  if (!body.includes("n***@example.com") && !body.includes("***@")) throw new Error("Masked email was not shown.");
  await page.getByRole("button", { name: "Confirm unsubscribe" }).click();
  await page.getByText("You have been unsubscribed", { exact: false }).waitFor({ timeout: 20000 });
  console.log("PASS newsletter unsubscribe");

  const updated = query(`SELECT status, unsubscribed_at FROM newsletter_subscribers WHERE email='${email.replaceAll("'", "''")}';`);
  if (updated[0]?.status !== "unsubscribed" || !updated[0]?.unsubscribed_at) {
    throw new Error("Unsubscribe status was not persisted.");
  }
  console.log("PASS unsubscribe persisted in D1");
} finally {
  await browser.close();
}
