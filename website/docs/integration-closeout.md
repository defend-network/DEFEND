# Owner-Assisted Integration Closeout

This is the one-at-a-time production closeout runbook. Do not paste secrets, API keys, passwords, recovery codes, or backup passphrases into chat. When a step is complete, say only "step N done"; verification will use dashboards, CI, health checks, and non-secret metadata.

Staging baseline: `https://defend-website-staging.owner-e75.workers.dev`

## 1. Cloudflare CI/CD permission

**Why:** allows GitHub Actions to deploy the staging Worker without manual OAuth.

**Dashboard location**

- Cloudflare dashboard: `dash.cloudflare.com`
- Select the staging account that owns `defend-website-staging` (currently `e751c8bfeee06d7a530609f81ee79a12`).
- Account API tokens: **Manage Account > Account API Tokens > Create Token > Custom token**. A user-owned token at **My Profile > API Tokens** also works if it is scoped to the same account.

**Minimum permissions**

- Account > Workers Scripts > Edit
- Account > D1 > Edit
- Account > R2 > Edit
- Account resources: include only the staging account
- Zone permissions: none for the current `workers.dev` hostname. Add Zone > Workers Routes > Edit only if a custom domain is connected later.

**You must do**

1. Create the token with the permissions above.
2. In GitHub: repository **Settings > Secrets and variables > Actions > Secrets > New repository secret**.
3. Name it `CLOUDFLARE_API_TOKEN`; paste the token only into the GitHub secret field.
4. Confirm the existing `CLOUDFLARE_ACCOUNT_ID` secret is `e751c8bfeee06d7a530609f81ee79a12`.
5. In **Variables**, set `ENABLE_STAGING_DEPLOY` to `true`.
6. Revoke the token immediately if it is ever exposed.

**Verification I will perform**

- `gh pr checks` shows **Deploy staging Worker** as pass, not skipped.
- `npx wrangler deployments list --env staging` shows a new CI-authored version.
- Staging `/api/health` still reports `ok`, `staging`, database connected, payments test.

## 2. Staging owner bootstrap and MFA

**Why:** the staging admin portal currently has no owner account.

**You must do**

From the repository `website` directory:

```powershell
npm run bootstrap:owner -- --remote --env=staging --expected-d1-id=39ff28d5-dc0b-4927-a6bc-81ddbae6ca6b
```

Enter the owner email, display name, and a unique password of at least 12 characters at the hidden prompts. Store the password in your password manager, not in chat or Git.

Then:

1. Sign in at `https://defend-website-staging.owner-e75.workers.dev/login`.
2. Open **Admin > Security / MFA**.
3. Complete TOTP enrollment with an authenticator app.
4. Store recovery codes offline.
5. Sign out, sign in again, and confirm the MFA challenge.
6. Leave at least one second owner/admin recovery path documented before production.

**Verification I will perform**

- Staging `/admin` redirects to login when signed out.
- Owner sign-in reaches `/admin`.
- A second sign-in requires the MFA challenge.
- Audit events show owner bootstrap, MFA enrollment, and sign-in activity without secret values.

## 3. Resend transactional email

**Why:** replace the development outbox with real transactional delivery.

**Dashboard location**

- `resend.com` > **API Keys** > **Create API Key**
- `resend.com` > **Domains** > **Add Domain**
- Cloudflare dashboard > the `defend-network.org` zone (or `sparkling-standard.com` for a staging subdomain) > **DNS > Records**

**You must do**

1. Create a Resend API key with **Sending access**, restricted to the verified sending domain.
2. Add the domain in Resend.
3. Add every DKIM, SPF, MX, and DMARC record Resend provides to Cloudflare DNS. Do not proxy mail records.
4. Wait for Resend to show the domain as verified.
5. Store the API key as a Worker secret. From `website`, run and paste only at the hidden prompt:

```powershell
npx wrangler secret put RESEND_API_KEY --env staging
```

6. Set non-secret variables in `wrangler.jsonc` or dashboard: `EMAIL_TRANSPORT=resend`, `EMAIL_FROM=DEFEND <updates@your-verified-domain>`.
7. Deploy staging through CI or manually.
8. Send one transactional test only: submit a membership application or use the verification email action.

**Verification I will perform**

- Staging **Admin > Communications** shows provider `resend`, status `sent`, and a provider message ID.
- Resend dashboard shows delivered, not just accepted.
- Development outbox is no longer used for that message.
- No bulk newsletter or campaign send is executed.
- Unsubscribe links will be generated for future newsletter mail; current transactional templates do not include a newsletter unsubscribe footer.

## 4. Turnstile production keys

**Why:** staging currently uses Cloudflare test keys, which prove integration but not spam resistance.

**Dashboard location**

- Cloudflare dashboard > **Turnstile** > **Add widget**
- Widget settings: hostnames for staging and, later, production

**You must do**

1. Add the staging hostname `defend-website-staging.owner-e75.workers.dev`.
2. Add production hostnames later only after authorization: `defend-network.org` and `www.defend-network.org`.
3. Choose Managed mode.
4. Put the public site key in the build environment as `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.
5. Store the secret only as the Worker secret `TURNSTILE_SECRET_KEY`.
6. Never use production Turnstile keys in a local build.

**Verification I will perform**

- The new widget renders on staging.
- A valid challenge submits successfully.
- Removing the Turnstile response is rejected with a spam-check failure.
- Production remains fail-closed if `TURNSTILE_SECRET_KEY` is absent.

## 5. Stripe test mode only

**Why:** exercise the payment code without enabling live charges.

**Dashboard location**

- `dashboard.stripe.com/test`
- **Developers > API keys**
- **Product catalog > Add product** for the membership price
- **Developers > Webhooks > Add endpoint**

**Minimum setup**

- Test secret key
- Recurring test price ID
- Webhook endpoint `https://defend-website-staging.owner-e75.workers.dev/api/webhooks/stripe`
- Events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`

**You must do**

1. Stay in **Test mode**. Do not activate live payments.
2. Store `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, and `STRIPE_WEBHOOK_SECRET` as Worker secrets.
3. Keep `PAYMENTS_MODE=test`, `PAYMENTS_LIVE_APPROVED=false`, `DONATIONS_ENABLED=false`.
4. Use Stripe test card `4242 4242 4242 4242` for one staging checkout.
5. Exercise cancel, failed payment, duplicate webhook, and customer portal where implemented.

**Verification I will perform**

- Staging billing shows test mode and no live-charge claim.
- Checkout returns and writes the expected test payment/subscription records.
- Duplicate webhook delivery is idempotent.
- No live key, live price, live donation, or live charge is used.

## 6. Analytics and search verification

**Dashboard locations**

- Cloudflare dashboard > **Analytics & Logs > Web Analytics > Add a site**
- Google Search Console: `search.google.com/search-console` > Add property
- Bing Webmaster Tools: `bing.com/webmasters` > Add site

**You must do**

1. Create a Cloudflare Web Analytics site and copy the beacon token.
2. Add a Google Search Console property using DNS verification (preferred) or the provided HTML meta value.
3. Add the Bing site and use the `msvalidate.01` meta value.
4. Set build/runtime values: `NEXT_PUBLIC_CF_WEB_ANALYTICS_TOKEN`, `GOOGLE_SITE_VERIFICATION`, `BING_SITE_VERIFICATION`.
5. Do not add advertising pixels or third-party trackers in this closeout.

**Verification I will perform**

- Cloudflare beacon appears only on public pages.
- Google/Bing verification meta tags appear in the deployed HTML.
- Search Console and Bing report verified ownership.
- No analytics token is committed.

## 7. Real-device camera check-in

**You must do**

1. Open the staging site on a real phone over HTTPS.
2. Sign in as an authorized admin.
3. Open **Admin > Check-in**.
4. Select a published event with an existing member registration.
5. Scan the member card QR code with the phone camera.
6. Confirm check-in succeeds, then repeat with a manually pasted token.

**Verification I will perform**

- Browser camera permission prompt appears only after the scan button is pressed.
- A real scan produces a short-lived token and successful check-in.
- Denying camera permission leaves the manual token path usable.
- No member data is exposed in the QR payload beyond the signed short-lived token.

## 8. Automated encrypted offsite backups

**Why:** D1 exports must leave Cloudflare and be recoverable.

**Prepared implementation**

- `website/scripts/backup-d1.mjs` exports D1 and encrypts it with AES-256-GCM and scrypt.
- `website/scripts/verify-backup.mjs` decrypts and validates table definitions and checksum.
- `.github/workflows/website-backup.yml` runs daily at 07:15 UTC when enabled and uploads a 90-day encrypted GitHub Actions artifact.
- Local drill passed: encrypted backup restored to SQL with 57 table definitions.

**You must do**

1. Create a unique `BACKUP_PASSPHRASE` of at least 20 characters and store it offline in the password manager.
2. Add it as GitHub repository secret `BACKUP_PASSPHRASE`.
3. Confirm `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are present.
4. Set repository variable `ENABLE_STAGING_BACKUPS=true`.
5. Run **Actions > DEFEND Staging Backup > Run workflow** once manually.
6. Download the encrypted artifact and perform an offline decrypt drill:

```powershell
$env:BACKUP_PASSPHRASE = "<from password manager>"
npm run backup:verify -- --file=<downloaded.enc> --out=restored.sql
```

For production, add a second copy to an S3-compatible bucket with separate credentials; GitHub artifacts alone are not a sufficient production retention policy.

**Verification I will perform**

- Backup workflow passes and uploads artifact.
- Checksum matches the manifest.
- Decrypted SQL contains more than 50 tables.
- Restore is performed only into an isolated database, never over staging or production.

## 9. Production account and DNS access

**You must do**

1. Identify the Cloudflare account that owns the `defend-network.org` zone.
2. Grant the minimum deployment identity without changing DNS yet.
3. Confirm the production Worker, D1, and R2 resources or approve creating them.
4. Do not change production DNS nameservers, records, or Worker routes in this closeout.

**Verification I will perform**

- Account and zone ownership are confirmed by an owner-authenticated dashboard or scoped token metadata.
- No production DNS or Worker deployment occurs.
- Production remains explicitly **NO-GO** until the launch checklist is signed.

## Legal and organizational actions

These are not technical integration tasks and cannot be verified from code:

- Incorporation status and registered agent
- 501(c)(3) application/counsel review
- Bylaws and membership criteria
- Privacy policy and terms of use
- Florida charitable solicitation registration
- Youth safeguarding and volunteer screening policy
- Insurance and payment/refund policy
- Data retention and member deletion policy
- Accessibility statement and complaint process
