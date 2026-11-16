import { chromium } from "playwright-core";
import path from "node:path";

const baseURL = process.env.A11Y_BASE_URL ?? "http://localhost:8787";
const edgePath = process.env.E2E_BROWSER_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const axePath = path.resolve("node_modules/axe-core/axe.min.js");
const password = process.env.E2E_OWNER_PASSWORD;
if (!password) throw new Error("Set E2E_OWNER_PASSWORD for the local test owner.");

const adminPaths = [
  "/admin",
  "/admin/applications",
  "/admin/chapters",
  "/admin/check-in",
  "/admin/communications",
  "/admin/crm",
  "/admin/documents",
  "/admin/events",
  "/admin/facilities",
  "/admin/finance",
  "/admin/members",
  "/admin/programs",
  "/admin/security",
  "/admin/system",
  "/admin/website",
];
const memberPaths = [
  "/members",
  "/members/account",
  "/members/account/security",
  "/members/billing",
  "/members/card",
  "/members/directory",
  "/members/volunteers",
];

async function runAxe(page, label, total) {
  const result = await page.evaluate(async () => {
    return await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
    });
  });
  total.count += result.violations.length;
  console.log(`\n${label}: ${result.violations.length} violations`);
  for (const violation of result.violations) {
    console.log(`- ${violation.id} [${violation.impact}] ${violation.help}`);
    for (const node of violation.nodes.slice(0, 4)) console.log(`  ${node.target.join(" ")}`);
  }
}

const browser = await chromium.launch({ executablePath: edgePath, headless: true });
const total = { count: 0 };
try {
  const publicPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await publicPage.addInitScript({ path: axePath });
  await publicPage.goto(`${baseURL}/`, { waitUntil: "domcontentloaded" });
  await publicPage.waitForTimeout(1000);
  const overflow = await publicPage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(`mobile-overflow: ${overflow}px`);
  if (overflow > 1) throw new Error(`Mobile horizontal overflow: ${overflow}px`);
  await publicPage.getByRole("button", { name: "Open navigation menu" }).click();
  await publicPage.getByRole("navigation", { name: "Mobile" }).waitFor();
  const mobileLinks = await publicPage.getByRole("navigation", { name: "Mobile" }).getByRole("link").count();
  if (mobileLinks < 6) throw new Error(`Mobile navigation has only ${mobileLinks} links`);
  console.log(`mobile-navigation: ${mobileLinks} links visible`);
  await runAxe(publicPage, "/ (mobile menu open)", total);
  await publicPage.getByRole("button", { name: "Close navigation menu" }).click();
  await publicPage.close();

  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  await page.addInitScript({ path: axePath });
  page.on("pageerror", (error) => console.log("PAGEERROR", error.message));
  await page.goto(`${baseURL}/login`, { waitUntil: "load" });
  await page.waitForTimeout(1000);
  await page.locator("#email").fill("owner.e2e@example.com");
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/(members|login\/two-factor)/, { timeout: 30000 });
  if (page.url().includes("/login/two-factor")) {
    throw new Error("Owner MFA is enabled. Disable MFA for the local test owner or use the manual walkthrough.");
  }
  for (const route of adminPaths) {
    await page.goto(`${baseURL}${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await runAxe(page, route, total);
  }

  const memberState = process.env.E2E_MEMBER_STATE;
  if (memberState) {
    const memberContext = await browser.newContext({ storageState: memberState, viewport: { width: 1440, height: 1000 } });
    const memberPage = await memberContext.newPage();
    await memberPage.addInitScript({ path: axePath });
    for (const route of memberPaths) {
      await memberPage.goto(`${baseURL}${route}`, { waitUntil: "networkidle" });
      await memberPage.waitForTimeout(500);
      await runAxe(memberPage, route, total);
    }
    await memberContext.close();
  } else {
    console.log("\nmember-pages: skipped (set E2E_MEMBER_STATE)");
  }
  await context.close();
  console.log(`\nTOTAL VIOLATIONS: ${total.count}`);
  if (total.count > 0) process.exitCode = 1;
} finally {
  await browser.close();
}
