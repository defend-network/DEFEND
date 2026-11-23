# Owner Walkthrough

Use the staging URL only: `https://defend-website-staging.owner-e75.workers.dev`.

This walkthrough verifies the public site, member portal, admin portal, mobile navigation, documents, CRM, chapters, events, volunteers, finance, CMS, communications, and security. It is a human confirmation of the automated tests; do not use production credentials or production data.

## Before starting

- Use a desktop browser and a real phone on the staging URL.
- Use a staging owner account, not a production account.
- Do not upload real identity documents, real member data, or private notes.
- Do not send bulk email, activate live payments, or enable donations.
- Keep a notebook for anything that looks wrong: page, control, expected result, actual result.

## 1. Public website

Open each route:

- `/`
- `/about`
- `/programs`
- `/programs/<program>`
- `/membership`
- `/apply`
- `/contact`
- `/support`
- `/volunteer`
- `/events`
- `/news`
- `/newsletter`
- `/login`

Check:

- [ ] Header logo returns home.
- [ ] Desktop navigation contains About, Programs, Chapters, Membership, Events, News, and other configured links.
- [ ] “Member login” and “Apply for Membership” reach the correct pages.
- [ ] Footer organization, member, and get-involved groups work.
- [ ] Every page has one clear H1 and readable body copy.
- [ ] No horizontal scrolling at 1440px or 390px.
- [ ] No console errors on load.
- [ ] Organization status copy says DEFEND is not incorporated and has no IRS recognition.
- [ ] No live dues, donation, or payment claim is displayed.

## 2. Mobile navigation

On a 390px-wide viewport or phone:

- [ ] Hamburger button is visible and at least 44px.
- [ ] Opening it shows **Site navigation** with all configured links.
- [ ] Each link closes the sheet and navigates.
- [ ] Close button is reachable and closes the sheet.
- [ ] Focus does not escape into the page behind the sheet.
- [ ] Keyboard Escape closes the sheet.
- [ ] Member login and Apply buttons work.
- [ ] No horizontal overflow appears after opening and closing.

## 3. Public forms

### Membership application

- [ ] Required fields show useful errors.
- [ ] Interest, volunteer, and program checkboxes work.
- [ ] Consent checkboxes are required.
- [ ] Submission returns an application number.
- [ ] The applicant receives a received-email event in the outbox or Resend history.
- [ ] Duplicate email behavior is understandable.
- [ ] Referral/UTM values are recorded when the URL contains `ref`, `utm_source`, `utm_medium`, or `utm_campaign`.

### Contact

- [ ] Required fields validate.
- [ ] Turnstile widget appears when configured.
- [ ] Submission shows a confirmation.
- [ ] A contact event appears in admin communications.

### Newsletter

- [ ] Email validation works.
- [ ] Consent is required.
- [ ] Turnstile widget appears when configured.
- [ ] A new email subscribes.
- [ ] Re-submitting the same email does not create a duplicate.
- [ ] The unsubscribe link opens a confirmation page with a masked address.
- [ ] Confirming unsubscribe updates the subscriber to `unsubscribed`.
- [ ] An invalid or altered token shows an error and does not change any record.
- [ ] Admin communications shows the subscriber count.

## 4. Owner sign-in and MFA

- [ ] `/login` shows email and password fields.
- [ ] A failed password shows an error and does not disclose whether the email exists.
- [ ] A valid password reaches `/members` or the MFA challenge.
- [ ] `/admin` is inaccessible when signed out.
- [ ] `/admin` is accessible after owner sign-in.
- [ ] MFA enrollment requires the current password.
- [ ] A TOTP code enables MFA.
- [ ] Recovery codes are displayed once and can be stored offline.
- [ ] Signing out and back in requires MFA.
- [ ] A wrong TOTP code is rejected.

## 5. Owner/admin portal

Walk each module from the admin sidebar:

### Overview `/admin`

- [ ] Applicant, member, chapter, document, and recent activity summaries are visible.
- [ ] Links lead to the corresponding module.
- [ ] No count includes data outside the owner’s authorized scope.

### Applications `/admin/applications`

- [ ] Status filter works.
- [ ] Search works.
- [ ] Open a submitted application.
- [ ] Request information creates a secure applicant update link.
- [ ] Approve creates an invitation.
- [ ] Deny requires a reason.
- [ ] Review history and audit details are visible.
- [ ] Referral and UTM source display correctly.

### Members `/admin/members`

- [ ] Member list and search work.
- [ ] Open a member record.
- [ ] Standing update requires a reason and writes history.
- [ ] Roles and status are displayed without exposing secrets.
- [ ] Directory-related controls respect member preferences.

### Chapters `/admin/chapters`

- [ ] Create a chapter with name, county, state, status, and contact email.
- [ ] New chapters default to a proposed/in-development status, not operating.
- [ ] Update a chapter status; the change is visible after refresh.
- [ ] Chapter contact and description are saved.
- [ ] The public chapters page does not overstate an unapproved chapter.

### CRM `/admin/crm`

- [ ] Create an organization.
- [ ] Create a contact and link it to an organization.
- [ ] Create a lead with source, stage, and notes.
- [ ] Add an activity and a task.
- [ ] Open a lead detail page.
- [ ] No private notes appear on public or group surfaces.

### Facilities `/admin/facilities`

- [ ] Create a property.
- [ ] Create a project linked to the property.
- [ ] Record a partnership proposal.
- [ ] Project status and proposal values save.

### Documents `/admin/documents`

- [ ] Upload a small non-sensitive PDF under 10 MB.
- [ ] Title, description, category, and visibility save.
- [ ] Reject an unsupported MIME type or oversized file.
- [ ] The library search and category filter work.
- [ ] Open document detail.
- [ ] Preview opens inline for an authorized admin.
- [ ] Download requires authorization and writes a download audit event.
- [ ] Upload a replacement version.
- [ ] Version history shows both versions.
- [ ] Restore an earlier version without deleting the original object.
- [ ] Archive the document; it remains recoverable and the original R2 object is not deleted.
- [ ] A signed-out user cannot preview, download, or open the detail page.

### Events `/admin/events`

- [ ] Create a published event with title, summary, description, date, location, capacity, status, family-friendly flag, and fee fields where shown.
- [ ] The event appears on `/events`.
- [ ] Create a volunteer opportunity.
- [ ] Member registration and volunteer registration work.
- [ ] Admin check-in accepts a valid short-lived card token only for a registered member.
- [ ] Check-in rejects an unregistered member and reports why.
- [ ] Camera scanning works on a real phone; manual token entry remains available if permission is denied.

### Programs `/admin/programs`

- [ ] Create/edit a program.
- [ ] Set capacity, fee, family-friendly, and status.
- [ ] `planned` and `in_development` programs are not presented as operating services.
- [ ] The public programs page reads the database, not hard-coded content.

### Website/CMS `/admin/website`

- [ ] Create a draft page.
- [ ] Create a published article with title, slug, summary, and body.
- [ ] The article appears on `/news`.
- [ ] Editing creates a revision.
- [ ] A published page/article remains readable after refresh.
- [ ] Do not publish unreviewed private or legal content.

### Communications `/admin/communications`

- [ ] Transport status accurately shows outbox, Resend, or not configured.
- [ ] Delivery history shows template, recipient, provider, status, and time.
- [ ] Development outbox is visible only outside production.
- [ ] Newsletter subscriber count is shown.
- [ ] Bulk email remains disabled.

### Finance `/admin/finance`

- [ ] Record an expense with category, amount, date, and description.
- [ ] The expense appears in the finance list.
- [ ] Chapter allocation and sponsor contribution forms behave as labeled.
- [ ] Billing status says not configured or test mode; no fake live success.

### System `/admin/system`

- [ ] Role assignment requires a user, role, and scope.
- [ ] Assign an allowed role and see the audit event.
- [ ] The role matrix does not allow an unknown role to be submitted.
- [ ] Integration status is honest: Turnstile, Resend, Stripe, and analytics show configured/not configured accurately.

### Security/MFA `/admin/security`

- [ ] MFA status is visible.
- [ ] Enrollment requires the current password.
- [ ] TOTP verification succeeds with a current code.
- [ ] Recovery code generation is available and displayed once.
- [ ] Owner-assisted reset is available only to an authorized owner.
- [ ] Audit events record security actions without secrets.

### Audit and dev-only pages

- [ ] Admin audit events show the latest actions.
- [ ] `/dev/outbox` works only outside production and is not linked in production.

## 6. Member workflow

Use an approved test applicant, never real member data.

- [ ] Application submitted.
- [ ] Admin requests information; secure link works once.
- [ ] Applicant updates and submits the response.
- [ ] Admin approves and creates an invitation.
- [ ] Invitation activation sets a password and signs the member in.
- [ ] Member dashboard shows status and next actions.
- [ ] Profile phone, profession, skills, interests, and directory preferences save.
- [ ] Opting into the directory shows the member there; opting out hides them.
- [ ] Digital card shows a short-lived QR token, not personal data.
- [ ] Event registration confirms.
- [ ] Volunteer registration confirms.
- [ ] Billing states not configured/test; no payment is taken.
- [ ] Password reset via outbox/Resend works and revokes old sessions where applicable.
- [ ] Member-to-member directory data is limited to the member policy.

## 7. Document authorization checks

- [ ] Signed-out access to `/admin/documents` redirects to login.
- [ ] Signed-out access to a document preview/download is denied.
- [ ] A member cannot access private admin documents.
- [ ] A chapter-scoped user cannot read another chapter’s private document if chapter restrictions are configured.
- [ ] Preview response uses inline content disposition and an authorized MIME type.
- [ ] Download audit events exist after a successful download.
- [ ] Archived documents are excluded from normal active lists but remain recoverable.

## 8. Mobile admin and member checks

At 390px:

- [ ] Admin sidebar/navigation remains usable without horizontal clipping.
- [ ] Tables scroll inside their own container, not the whole page.
- [ ] Document and member action buttons remain reachable.
- [ ] Member card and QR code fit the viewport.
- [ ] Forms remain keyboard- and screen-reader-usable.
- [ ] No text overlap or cut-off headings.

## 9. Accessibility spot checks

- [ ] Keyboard Tab reaches logo, navigation, forms, and buttons in a logical order.
- [ ] Focus is visible on links and buttons.
- [ ] Error messages are announced or associated with their fields.
- [ ] Form labels are programmatically associated.
- [ ] Images have appropriate alt text; decorative images are ignored.
- [ ] No color-only status communication.
- [ ] Reduced-motion preference does not break navigation.
- [ ] Run `node scripts/accessibility-audit.mjs` and `node scripts/accessibility-auth-audit.mjs` against local; both report 0 violations.

## 10. Recovery and closeout

- [ ] Run the local encrypted backup and decrypt drill.
- [ ] Confirm the backup workflow is enabled and produces an artifact.
- [ ] Document who holds the backup passphrase.
- [ ] Confirm no production DNS, Worker, payment, donation, or bulk email change occurred.
- [ ] Record any failed control in the launch checklist.

## Automated coverage matrix

| Area | Automated evidence |
|---|---|
| Public routes | `scripts/accessibility-audit.mjs` |
| Mobile menu | `scripts/accessibility-auth-audit.mjs` |
| Admin/member routes | `scripts/accessibility-auth-audit.mjs` |
| Application-to-member lifecycle | `scripts/e2e-membership.mjs` (33 checks) |
| Documents, CRM, chapters, events, finance, CMS, communications | `scripts/e2e-membership.mjs` |
| Newsletter subscription/unsubscribe | `scripts/e2e-newsletter.mjs` |
| D1 encrypted backup/decrypt | `scripts/backup-d1.mjs` + `scripts/verify-backup.mjs` |
