# Production Readiness

Production deployment is **not authorized**. The live `defend-network.org` site and DNS remain unchanged. This document records the Milestone 4 readiness state and the gates that still require owner action.

## Environment status

| Item | Status |
|---|---|
| Staging URL | `https://defend-website-staging.owner-e75.workers.dev` |
| Staging Worker version | `084f2433-565e-4ea5-9326-7c8951cb05be` |
| Staging D1 migrations | `0000`-`0009` applied |
| Staging programs | 7 seeded / database-backed |
| Staging newsletter | Verified signup writes to D1 |
| Staging Turnstile | Cloudflare test keys |
| Staging email | Development outbox only |
| Staging payments | Test mode, live charging disabled |

The currently available Cloudflare account owns the staging Worker and `sparkling-standard.com`, not `defend-network.org`. The production zone uses different nameservers. Production requires an owner-supplied deployment credential and explicit authorization.

## Implemented in Milestone 4

- Administrative modules for CRM, facilities, chapters, documents, CMS/news, communications, finance, programs, events, volunteers, check-in, roles, and audit.
- Private document upload/list, authorized inline preview, version history, restore, and archive without deleting the original object.
- Database-backed public programs and seeded program content.
- Newsletter subscription with consent, duplicate reactivation, rate limiting, honeypot, and Turnstile support.
- Application referral and UTM capture with administrative display.
- Static CSP and security headers; auth forms use POST so password fallback submissions do not enter URLs.
- WCAG 2.2 AA axe audit covering 10 public routes with zero violations.
- D1 export/restore and R2 object recovery drills.
- 29-check membership/admin end-to-end workflow.

## Blocking owner actions

1. Create a scoped Cloudflare API token for the staging account (Workers Scripts:Edit, D1:Edit, R2:Edit), store it as the GitHub `CLOUDFLARE_API_TOKEN` secret, then set `ENABLE_STAGING_DEPLOY=true`.
2. Bootstrap the staging owner: `npm run bootstrap:owner -- --remote --env staging`. The password must be entered interactively and never committed.
3. Provide Resend production credentials, verified sending domain, and SPF/DKIM/DMARC records.
4. Provide real Turnstile site/secret keys for production. Staging test keys do not prove spam resistance.
5. Provide Stripe test keys, price ID, and webhook secret; complete test-mode checkout, renewal, failure, cancellation, refund, and duplicate-webhook exercises before live approval.
6. Provide Google Search Console, Bing Webmaster, and Cloudflare Web Analytics verification tokens.
7. Complete a real-device camera QR scan test.
8. Confirm production Cloudflare account access and the production zone ownership path.
9. Complete legal review: incorporation, 501(c)(3) counsel, membership policy, privacy/terms, Florida solicitation registration, and youth safeguarding.
10. Decide and document the backup schedule for D1 exports and R2 object versions.

## Production gates

- No production DNS or Worker deployment without explicit owner authorization.
- No live card charging or donation activation until processor, finance, legal, and owner readiness are confirmed.
- No bulk email until Resend delivery and unsubscribe handling are verified.
- No production owner bootstrap until the production D1 database and secrets are provisioned.
- Migrations must be applied to a production copy and verified before cutover.
- A D1 export must be taken immediately before destructive migrations.
- Roll back Workers by version and D1 by Time Travel; restore R2 from dated backups.
- Re-run the full E2E, accessibility, authorization matrix, and backup/restore checks against the production candidate.

## Known residual gaps

- CSP uses `'unsafe-inline'` for Next.js bootstrap scripts. A nonce policy caused cached-HTML hydration failures under OpenNext and was removed; cache-safe nonce delivery remains pending.
- Funnel reporting is limited to referral/UTM capture and administrative display.
- Newsletter unsubscribe flow is not implemented because bulk email is not enabled.
- Automated remote backups are documented but not scheduled.
- Manual screen-reader testing has not been performed.
- Production secrets, email, payments, analytics, and Turnstile are not configured.
