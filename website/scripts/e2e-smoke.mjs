import { chromium } from "playwright-core";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8787";
const edgePath =
  process.env.E2E_BROWSER_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const unique = Date.now().toString(36);
const applicantEmail = `e2e.applicant.${unique}@example.com`;
const contactEmail = `e2e.contact.${unique}@example.com`;

async function waitForTurnstile(page) {
  await page.waitForFunction(
    () => {
      const input = document.querySelector(
        'input[name="cf-turnstile-response"]',
      );
      return Boolean(input && input.value.length > 0);
    },
    { timeout: 30_000 },
  );
}

const browser = await chromium.launch({
  executablePath: edgePath,
  headless: true,
});

const page = await browser.newPage();
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(error.message));

try {
  await page.goto(`${baseURL}/`, { waitUntil: "domcontentloaded" });
  await page
    .getByRole("heading", {
      name: "A fraternal network built for the next generation.",
    })
    .waitFor();
  console.log("home: pass");

  await page.goto(`${baseURL}/apply`, { waitUntil: "domcontentloaded" });
  await page.locator("#legalName").fill("E2E Applicant");
  await page.locator("#preferredName").fill("E2E");
  await page.locator("#email").fill(applicantEmail);
  await page.locator("#phone").fill("555-0100");
  await page.locator("#city").fill("New Port Richey");
  await page.locator("#state").fill("FL");
  await page.locator("#postalCode").fill("34652");
  await page
    .locator('input[name="interests"][value="Cultural heritage"]')
    .check();
  await page
    .locator('input[name="volunteerInterests"][value="Community service"]')
    .check();
  await page.locator("#skills").fill("Carpentry and small business operations");
  await page
    .locator('input[name="programInterests"][value="Mentorship"]')
    .check();
  await page
    .getByRole("checkbox", { name: /I have read the membership information/i })
    .check();
  await page
    .getByRole("checkbox", { name: /I acknowledge that DEFEND will use/i })
    .check();
  await page
    .getByRole("checkbox", { name: /I confirm that I am 18/i })
    .check();
  await waitForTurnstile(page);
  await page.getByRole("button", { name: "Submit application" }).click();
  await page
    .getByText("Your application has been received", { exact: false })
    .waitFor({ timeout: 30_000 });
  const applicationNumber =
    (await page.locator("p.font-mono").first().textContent())?.trim() ?? "";
  console.log(`apply: pass ${applicationNumber}`);

  await page.goto(`${baseURL}/contact`, { waitUntil: "domcontentloaded" });
  await page.locator("#name").fill("E2E Contact");
  await page.locator("#email").fill(contactEmail);
  await page.locator("#subject").fill("E2E verification message");
  await page
    .locator("#message")
    .fill("This is an automated end-to-end verification message.");
  await waitForTurnstile(page);
  await page.getByRole("button", { name: "Send message" }).click();
  await page
    .getByText("Thank you. Your message has been received", { exact: false })
    .waitFor({ timeout: 30_000 });
  console.log("contact: pass");

  if (consoleErrors.length) {
    console.error("console errors:", consoleErrors);
    process.exitCode = 1;
  } else {
    console.log("console: no errors");
  }
} finally {
  await browser.close();
}
