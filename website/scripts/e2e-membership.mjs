import { chromium } from "playwright-core";
import * as OTPAuth from "otpauth";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8787";
const edgePath =
  process.env.E2E_BROWSER_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

const run = Date.now().toString(36);
const ownerEmail = "owner.e2e@example.com";
const ownerPassword = process.env.E2E_OWNER_PASSWORD;
if (!ownerPassword) {
  throw new Error("Set E2E_OWNER_PASSWORD for the local test owner.");
}
const applicantEmail = `membership.e2e.${run}@example.com`;
const applicantPassword = `MemberE2E-${run}-Password-2026!`;
const newMemberPassword = `MemberE2E-${run}-Reset-Password-2026!`;

const browser = await chromium.launch({
  executablePath: edgePath,
  headless: true,
});

const results = [];
function pass(label) {
  results.push(label);
  console.log(`PASS ${label}`);
}

const applicantContext = await browser.newContext();
const applicant = await applicantContext.newPage();
const ownerContext = await browser.newContext();
const owner = await ownerContext.newPage();
let totp;

try {
  // 1. Public application submission
  await applicant.goto(`${baseURL}/apply`, { waitUntil: "domcontentloaded" });
  await applicant.locator("#legalName").fill("E2E Membership Applicant");
  await applicant.locator("#preferredName").fill("E2E Member");
  await applicant.locator("#email").fill(applicantEmail);
  await applicant.locator("#phone").fill("555-0199");
  await applicant.locator("#city").fill("New Port Richey");
  await applicant.locator("#state").fill("FL");
  await applicant.locator("#postalCode").fill("34652");
  await applicant.locator('input[name="interests"][value="Cultural heritage"]').check();
  await applicant.locator('input[name="volunteerInterests"][value="Events"]').check();
  await applicant.locator('input[name="programInterests"][value="Mentorship"]').check();
  await applicant.locator("#skills").fill("Carpentry, small business operations");
  await applicant.getByRole("checkbox", { name: /I have read the membership information/i }).check();
  await applicant.getByRole("checkbox", { name: /I acknowledge that DEFEND will use/i }).check();
  await applicant.getByRole("button", { name: "Submit application" }).click();
  await applicant.getByText("Your application has been received", { exact: false }).waitFor({ timeout: 30000 });
  const applicationNumber = (await applicant.locator("p.font-mono").first().textContent())?.trim();
  pass(`application submitted ${applicationNumber}`);

  // 2. Owner sign-in and MFA enrollment
  await owner.goto(`${baseURL}/login`, { waitUntil: "load" });
  await owner.waitForTimeout(1000);
  await owner.locator("#email").fill(ownerEmail);
  await owner.locator("#password").fill(ownerPassword);
  await owner.getByRole("button", { name: "Sign in" }).click();
  await owner.waitForURL(/\/members/, { timeout: 30000 });
  pass("owner password sign-in");

  await owner.goto(`${baseURL}/admin/security`, { waitUntil: "networkidle" });
  const enableResponse = owner.waitForResponse(
    (response) =>
      response.url().includes("/api/auth/two-factor/enable") &&
      response.request().method() === "POST",
  );
  await owner.locator("#enable-password").fill(ownerPassword);
  await owner.getByRole("button", { name: "Start MFA enrollment" }).click();
  const enablePayload = await (await enableResponse).json();
  const totpURI = enablePayload.totpURI;
  if (!totpURI) throw new Error(`MFA enrollment did not return a TOTP URI: ${JSON.stringify(enablePayload)}`);
  totp = OTPAuth.URI.parse(totpURI);
  await owner.locator("#totp-code").fill(totp.generate());
  await owner.getByRole("button", { name: "Verify and enable MFA" }).click();
  await owner.getByText("Multi-factor authentication is enabled", { exact: false }).waitFor({ timeout: 30000 });
  pass("owner MFA enrolled");

  // 3. Admin application review and approval
  await owner.goto(`${baseURL}/admin/applications?status=submitted`, { waitUntil: "networkidle" });
  await owner.getByRole("link", { name: "Review", exact: true }).first().click();
  await owner.waitForURL(/\/admin\/applications\/app_/);

  await owner.locator("#info-message").fill("Please confirm your trade experience.");
  await owner.getByRole("button", { name: "Request information" }).click();
  await owner.getByText("Information request saved", { exact: false }).waitFor({ timeout: 30000 });
  const updateUrl = (await owner.locator("code").first().textContent())?.trim();
  if (!updateUrl) throw new Error("Application update URL was not displayed");

  await applicant.goto(updateUrl, { waitUntil: "domcontentloaded" });
  await applicant.locator("#city").fill("Port Richey");
  await applicant.locator("#skills").fill("Carpentry, framing, small business operations");
  await applicant.getByRole("button", { name: "Submit updated application" }).click();
  await applicant.getByText("Your application has been updated", { exact: false }).waitFor({ timeout: 30000 });
  pass("request-information and applicant update");

  await owner.reload({ waitUntil: "domcontentloaded" });
  await owner.locator("#approve-notes").fill("E2E verified application");
  await owner.getByRole("button", { name: "Approve and create invitation" }).click();
  await owner.getByText("Application approved", { exact: false }).waitFor({ timeout: 30000 });
  const activationUrl = (await owner.locator("code").first().textContent())?.trim();
  if (!activationUrl) throw new Error("Activation URL was not displayed");
  pass("application approved and invitation created");

  // 4. Activation and member sign-in
  const memberContext = await browser.newContext();
  const member = await memberContext.newPage();
  await member.goto(activationUrl, { waitUntil: "domcontentloaded" });
  await member.locator("#name").fill("E2E Member");
  await member.locator("#password").fill(applicantPassword);
  await member.locator("#confirmation").fill(applicantPassword);
  await member.getByRole("button", { name: "Activate account" }).click();
  await member.getByText("Your account is active", { exact: false }).waitFor({ timeout: 30000 });
  pass("invitation activation");

  await member.getByRole("link", { name: "Go to sign in" }).click();
  await member.locator("#email").fill(applicantEmail);
  await member.locator("#password").fill(applicantPassword);
  await member.getByRole("button", { name: "Sign in" }).click();
  await member.waitForURL(/\/members/, { timeout: 30000 });
  await member.getByRole("heading", { name: /Welcome/i }).waitFor();
  pass("member sign-in and dashboard");

  // 5. Profile and directory settings
  await member.goto(`${baseURL}/members/account`, { waitUntil: "domcontentloaded" });
  await member.locator("#phone").fill("555-0177");
  await member.locator("#profession").fill("Carpenter");
  await member.locator("#skills").fill("Framing, finish carpentry");
  await member.locator('input[name="directoryVisible"]').check();
  await member.locator('input[name="showChapter"]').check();
  await member.locator('input[name="showProfession"]').check();
  await member.locator('input[name="showSkills"]').check();
  await member.getByRole("button", { name: "Save profile and preferences" }).click();
  await member.getByText("Profile and preferences updated", { exact: false }).waitFor({ timeout: 30000 });
  pass("member profile and directory preferences");

  await member.goto(`${baseURL}/members/directory`, { waitUntil: "domcontentloaded" });
  await member.getByText("E2E Member", { exact: false }).first().waitFor();
  pass("opt-in directory entry visible");

  // 6. Digital card and token
  await member.goto(`${baseURL}/members/card`, { waitUntil: "domcontentloaded" });
  await member.getByText("Secure check-in code", { exact: false }).waitFor();
  const card = await member.evaluate(async () => {
    const response = await fetch("/api/members/card-token");
    return { ok: response.ok, body: await response.json() };
  });
  if (!card.ok || !card.body.token) throw new Error("Card token was not issued");
  pass("digital card token issued");

  // 7. Admin event creation and member registration
  await owner.goto(`${baseURL}/admin/events`, { waitUntil: "networkidle" });
  const eventTitle = `E2E Founding Gathering ${run}`;
  await owner.locator("#title").fill(eventTitle);
  await owner.locator("#summary").fill("Founding chapter gathering for verification.");
  await owner.locator("#description").fill("This event verifies registration and check-in.");
  await owner.locator("#startsAt").fill("2026-12-15T18:00");
  await owner.locator("#locationName").fill("Pasco County");
  await owner.locator("#capacity").fill("25");
  await owner.locator("#status").selectOption("published");
  await owner.getByRole("button", { name: "Create event" }).click();
  await owner.getByText("Event created.", { exact: false }).waitFor({ timeout: 30000 });
  pass("admin event creation");

  await owner.locator("#vol-title").fill(`E2E Volunteer Opportunity ${run}`);
  await owner.locator("#vol-description").fill("Help with the founding gathering.");
  await owner.locator("#slots").fill("5");
  await owner.getByRole("button", { name: "Create opportunity" }).click();
  await owner.getByText("Volunteer opportunity created.", { exact: false }).waitFor({ timeout: 30000 });
  pass("admin volunteer opportunity creation");

  await member.goto(`${baseURL}/events`, { waitUntil: "domcontentloaded" });
  await member
    .getByText(eventTitle)
    .locator("xpath=ancestor::div[contains(@class,'flex h-full flex-col')][1]")
    .getByRole("link", { name: "Event details" })
    .click();
  await member.getByRole("button", { name: "Register for this event" }).click();
  await member.getByText("Your event registration is confirmed", { exact: false }).waitFor({ timeout: 30000 });
  pass("member event registration");

  await member.goto(`${baseURL}/members/volunteers`, { waitUntil: "domcontentloaded" });
  await member.getByRole("button", { name: "Register to volunteer" }).first().click();
  await member.getByText("Volunteer registration recorded", { exact: false }).waitFor({ timeout: 30000 });
  pass("member volunteer registration");

  // 8. Admin check-in with member card token and event
  await owner.goto(`${baseURL}/admin/check-in`, { waitUntil: "networkidle" });
  await owner.waitForTimeout(1000);
  await owner.locator("#eventId").selectOption({ label: eventTitle });
  await owner.locator("#token").fill(card.body.token);
  await owner.getByRole("button", { name: "Verify and check in" }).click();
  await owner.getByText("E2E Member", { exact: false }).waitFor({ timeout: 30000 });
  pass("event check-in with short-lived card token");

  // 9. Admin member management
  await owner.goto(`${baseURL}/admin/members`, { waitUntil: "networkidle" });
  await owner.getByRole("link", { name: "Manage" }).first().click();
  await owner.getByText("Member record", { exact: false }).waitFor();
  await owner.locator("#reason").fill("E2E founding access remains unpaid");
  await owner.getByRole("button", { name: "Update standing" }).click();
  await owner.getByText("Membership status updated", { exact: false }).waitFor({ timeout: 30000 });
  pass("admin member status update");

  // 9b. Administrative modules
  await owner.goto(`${baseURL}/admin/crm`, { waitUntil: "networkidle" });
  await owner.locator("#org-name").fill(`E2E Sponsor Org ${run}`);
  await owner.locator("#org-type").selectOption("sponsor");
  await owner.locator("#org-email").fill(`sponsor.${run}@example.com`);
  await owner.getByRole("button", { name: "Create organization" }).click();
  await owner.getByText("Organization created.", { exact: false }).waitFor({ timeout: 30000 });
  await owner.locator("#contact-first").fill("E2E");
  await owner.locator("#contact-last").fill("Contact");
  await owner.locator("#contact-email").fill(`contact.${run}@example.com`);
  await owner.getByRole("button", { name: "Create contact" }).click();
  await owner.getByText("Contact created.", { exact: false }).waitFor({ timeout: 30000 });
  await owner.locator("#lead-title").fill(`E2E Sponsorship Lead ${run}`);
  await owner.locator("#lead-type").selectOption("sponsor");
  await owner.getByRole("button", { name: "Create lead" }).click();
  await owner.getByText("Lead created.", { exact: false }).waitFor({ timeout: 30000 });
  pass("CRM organization, contact, and lead");

  await owner.goto(`${baseURL}/admin/facilities`, { waitUntil: "networkidle" });
  await owner.locator("#property-address").fill(`123 E2E Property ${run}`);
  await owner.locator("#property-city").fill("New Port Richey");
  await owner.locator("#property-state").fill("FL");
  await owner.getByRole("button", { name: "Create property lead" }).click();
  await owner.getByText("Property lead created.", { exact: false }).waitFor({ timeout: 30000 });
  await owner.locator("#project-name").fill(`E2E Facility Project ${run}`);
  await owner.getByRole("button", { name: "Create project" }).click();
  await owner.getByText("Facility project created.", { exact: false }).waitFor({ timeout: 30000 });
  await owner.locator("#proposal-title").fill(`E2E Property Proposal ${run}`);
  await owner.getByRole("button", { name: "Create proposal" }).click();
  await owner.getByText("Partnership proposal created.", { exact: false }).waitFor({ timeout: 30000 });
  pass("facilities property, project, and proposal");

  await owner.goto(`${baseURL}/admin/documents`, { waitUntil: "networkidle" });
  await owner.locator("#doc-file").setInputFiles({
    name: "e2e-document.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("DEFEND E2E document verification."),
  });
  await owner.locator("#doc-title").fill(`E2E Document ${run}`);
  await owner.locator("#doc-category").selectOption("governance");
  await owner.locator("#doc-visibility").selectOption("admin");
  await owner.getByRole("button", { name: "Upload document" }).click();
  await owner.getByText("Document uploaded.", { exact: false }).waitFor({ timeout: 30000 });
  await owner.getByText(`E2E Document ${run}`, { exact: false }).waitFor();
  pass("private document upload and listing");

  await owner.goto(`${baseURL}/admin/website`, { waitUntil: "networkidle" });
  await owner.locator("#page-title").fill(`E2E CMS Page ${run}`);
  await owner.locator("#page-text").fill("This page verifies CMS page creation.");
  await owner.getByRole("button", { name: "Create page" }).click();
  await owner.getByText("Page created", { exact: false }).waitFor({ timeout: 30000 });
  await owner.locator("#article-title").fill(`E2E News Update ${run}`);
  await owner.locator("#article-text").fill("This article verifies the public news workflow.");
  await owner.locator('input[type="checkbox"][name="publish"]').last().check();
  await owner.getByRole("button", { name: "Create article" }).click();
  await owner.getByText("Article created", { exact: false }).waitFor({ timeout: 30000 });
  await owner.goto(`${baseURL}/news`, { waitUntil: "networkidle" });
  await owner.getByText(`E2E News Update ${run}`, { exact: false }).waitFor();
  pass("CMS page, published article, and public news");

  await owner.goto(`${baseURL}/admin/programs`, { waitUntil: "networkidle" });
  await owner.locator("#program-title").fill(`E2E Family Workshop ${run}`);
  await owner.locator("#program-summary").fill("E2E family program verification.");
  await owner.locator("#program-capacity").fill("20");
  await owner.locator("#program-fee").fill("5");
  await owner.locator('input[name="familyFriendly"]').check();
  await owner.getByRole("button", { name: "Create program" }).click();
  await owner.getByText("Program created.", { exact: false }).waitFor({ timeout: 30000 });
  pass("program capacity, fee, and family configuration");

  await owner.goto(`${baseURL}/admin/chapters`, { waitUntil: "networkidle" });
  await owner.locator("#chapter-name").fill(`E2E Test County ${run}`);
  await owner.locator("#chapter-county").fill("Test");
  await owner.locator("#chapter-state").fill("FL");
  await owner.locator("#chapter-status").selectOption("proposed");
  await owner.getByRole("button", { name: "Create chapter" }).click();
  await owner.getByText("Chapter created.", { exact: false }).waitFor({ timeout: 30000 });
  pass("chapter creation as proposed, not operating");

  await owner.goto(`${baseURL}/admin/finance`, { waitUntil: "networkidle" });
  await owner.locator("#expense-vendor").fill(`E2E Vendor ${run}`);
  await owner.locator("#expense-amount").fill("12.34");
  await owner.locator("#expense-date").fill("2026-12-01T12:00");
  await owner.getByRole("button", { name: "Record expense" }).click();
  await owner.getByText("Expense recorded.", { exact: false }).waitFor({ timeout: 30000 });
  pass("finance expense recording");

  await owner.goto(`${baseURL}/admin/system`, { waitUntil: "networkidle" });
  const memberOption = await owner
    .locator("#role-user option", { hasText: applicantEmail })
    .getAttribute("value");
  if (!memberOption) throw new Error("Member option not found in system role form");
  await owner.locator("#role-user").selectOption(memberOption);
  await owner.locator("#role-key").selectOption("volunteer_coordinator");
  await owner.locator("#role-scope").selectOption("global");
  await owner.getByRole("button", { name: "Assign role" }).click();
  await owner.getByText("Role assigned.", { exact: false }).waitFor({ timeout: 30000 });
  pass("owner role assignment through system administration");

  await owner.goto(`${baseURL}/admin/communications`, { waitUntil: "networkidle" });
  await owner.getByRole("heading", { name: "Delivery history" }).waitFor();
  pass("communications delivery history");

  // 10. Password reset through development outbox
  await member.goto(`${baseURL}/forgot-password`, { waitUntil: "domcontentloaded" });
  await member.locator("#email").fill(applicantEmail);
  await member.getByRole("button", { name: "Request password reset" }).click();
  await member.getByText("If an account exists", { exact: false }).waitFor({ timeout: 30000 });
  await owner.goto(`${baseURL}/dev/outbox`, { waitUntil: "networkidle" });
  const outboxText = await owner.locator("pre").allTextContents();
  const resetText = outboxText.find((text) => text.includes("/api/auth/reset-password/"));
  if (!resetText) throw new Error("Password reset email was not found in the outbox");
  const resetMatch = resetText.match(/https?:\/\/[^\s]+\/api\/auth\/reset-password\/[^\s]+/);
  if (!resetMatch) throw new Error("Reset URL was not present in the email");
  const resetUrl = resetMatch[0];
  await member.goto(resetUrl, { waitUntil: "domcontentloaded" });
  await member.locator("#password").fill(newMemberPassword);
  await member.locator("#confirmation").fill(newMemberPassword);
  await member.getByRole("button", { name: "Reset password" }).click();
  await member.getByText("Your password has been reset", { exact: false }).waitFor({ timeout: 30000 });
  pass("password reset email and reset flow");

  // 11. Verify reset password works
  await member.goto(`${baseURL}/login`, { waitUntil: "domcontentloaded" });
  await member.locator("#email").fill(applicantEmail);
  await member.locator("#password").fill(newMemberPassword);
  await member.getByRole("button", { name: "Sign in" }).click();
  await member.waitForURL(/\/members/, { timeout: 30000 });
  pass("sign-in with reset password");

  // 12. MFA sign-in challenge for owner
  await owner.goto(`${baseURL}/admin`, { waitUntil: "networkidle" });
  await owner.getByRole("button", { name: "Sign out" }).click();
  await owner.waitForURL(baseURL + "/", { timeout: 30000 });
  await owner.goto(`${baseURL}/login`, { waitUntil: "load" });
  await owner.waitForTimeout(1000);
  await owner.locator("#email").fill(ownerEmail);
  await owner.locator("#password").fill(ownerPassword);
  await owner.getByRole("button", { name: "Sign in" }).click();
  await owner.waitForURL(/\/login\/two-factor/, { timeout: 30000 });
  await owner.locator("#code").fill(totp.generate());
  await owner.getByRole("button", { name: "Verify and continue" }).click();
  await owner.waitForURL(/\/members/, { timeout: 30000 });
  pass("owner MFA challenge on subsequent sign-in");

  // 13. Billing is honestly not configured
  await member.goto(`${baseURL}/members/billing`, { waitUntil: "domcontentloaded" });
  await member.getByText("Dues and payments", { exact: false }).waitFor();
  await member.getByText("Stripe test-mode credentials are not configured", { exact: false }).waitFor();
  pass("billing shows not configured, no fake success");

  console.log(`\nE2E RESULTS: ${results.length} checks passed`);
} finally {
  await browser.close();
}
