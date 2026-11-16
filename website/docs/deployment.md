# Deployment

## Current authorization

Production deployment is **not authorized** from this milestone. Do not change public DNS, deploy to `defend-network.org`, charge cards, send bulk email, or enable donations.

## Environments

| Environment | Worker | D1 | R2 | Payments |
|---|---|---|---|---|
| Local | Wrangler dev | local `.wrangler` | local | test/off |
| Staging | `defend-website-staging` | separate | separate | Stripe test |
| Production | `defend-website` | separate | separate | off until approved |

## Provisioning checklist

1. Create a D1 database for the environment with owner approval.
2. Replace the placeholder `database_id` in the environment-specific Wrangler config.
3. Create private R2 buckets and bindings.
4. Set secrets with `wrangler secret put`:
   - `BETTER_AUTH_SECRET`
   - `AUDIT_HASH_SALT`
   - `PII_ENCRYPTION_KEY`
   - `CARD_TOKEN_SECRET`
   - `TURNSTILE_SECRET_KEY` and `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
   - `RESEND_API_KEY`, `EMAIL_FROM`
   - `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`
5. Set `APP_ENV`, `APP_URL`, `EMAIL_TRANSPORT`, `PAYMENTS_MODE`, and feature flags.
6. Apply migrations with `wrangler d1 migrations apply DB --remote --env <environment>`.
7. Bootstrap the single owner with `npm run bootstrap:owner -- --remote --env <environment>`.
8. Build with `npm run build:worker`.
9. Deploy only with explicit authorization.

## Local verification

```powershell
npm run db:verify
npm test
npm run typecheck
npm run lint
npm run build
npm run build:worker
npm run preview
```

For the browser tests, keep the Worker running and use:

```powershell
npm run e2e:smoke
npm run e2e:membership
```

The full membership test requires a locally bootstrapped `owner.e2e@example.com` account. It covers application, request-information, approval, activation, member sign-in, profile, directory, card, event/volunteer registration, check-in, member status management, password reset, MFA challenge, and billing not-configured behavior.

## Rollback

- Workers versions can be rolled back through the Cloudflare dashboard or Wrangler.
- D1 point-in-time recovery is available through Time Travel; paid plans retain 30 days.
- Take a D1 export before destructive migrations.
- R2 objects must be restored from a dated backup prefix.

## Backups

- Scheduled D1 exports to a private R2 backup bucket.
- Dated R2 object backups for documents/media.
- Restore into an isolated staging environment and verify counts and access controls.
- No runtime databases or private data in Git.

## Email and DNS

Email delivery is not configured. Before enabling it:

- Configure Resend domain verification.
- Add SPF/DKIM/DMARC records with owner approval.
- Preserve existing Google Workspace MX records.
- Test delivery, bounce handling, and unsubscribe behavior.

## Production gate

A separate release report must document:

- exact commit,
- test results,
- security review,
- accessibility and performance checks,
- backup/restore verification,
- rollback plan,
- known gaps,
- explicit owner authorization.
