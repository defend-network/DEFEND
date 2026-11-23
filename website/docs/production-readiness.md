# Production Readiness

Related closeout documents:

- [Owner-assisted integration closeout](integration-closeout.md)
- [Owner walkthrough](owner-walkthrough.md)
- [Launch checklist](launch-checklist.md)

Production deployment is **not authorized**. The live `defend-network.org` site and DNS remain unchanged. This document records the Milestone 4 readiness state and the gates that still require owner action.

## Environment status

| Item | Status |
|---|---|
| Staging URL | `https://defend-website-staging.chairman-80b.workers.dev` |
| Staging Cloudflare account | `80be8ac2fd2e276114c056a283c6dc5c` |
| Staging Worker version | `90da8cc4-2ee3-493d-9ecb-0015cb407505` |
| Staging D1 | Dedicated DEFEND account, database `39ff28d5-dc0b-4927-a6bc-81ddbae6ca6b` |
| Staging D1 migrations | `0000`-`0013` applied; preserved staging rows imported |
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
- Newsletter subscription with consent, duplicate reactivation, rate limiting, honeypot, Turnstile support, and signed unsubscribe confirmation.
- Application referral and UTM capture with administrative display.
- Static CSP and security headers; auth forms use POST so password fallback submissions do not enter URLs.
- WCAG 2.2 AA axe audit: zero violations on 12 public routes and 22 authenticated admin/member routes, plus mobile menu verification.
- Encrypted AES-256-GCM D1 backup/decrypt drill and R2 object recovery drill; scheduled GitHub Actions backup workflow prepared.
- 33-check membership/admin workflow including document preview, version restore, archive, and authorization checks.

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
10. Enable the prepared encrypted backup workflow with `BACKUP_PASSPHRASE` and `ENABLE_STAGING_BACKUPS=true`; confirm artifact retention and add an S3-compatible production copy.

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
- Automated remote backup workflow is prepared but not enabled until owner secrets/variables are set.
- Manual screen-reader testing has not been performed.
- Production secrets, email, payments, analytics, and Turnstile are not configured.
