# DEFEND Website

Isolated organizational website, member portal, and administrative workstation for DEFEND.

**Branch:** `rebuild/website-platform-v1`

**Status:** Milestone 2 membership operations implemented and locally verified. This is not a production release.

## Implemented and verified

- Next.js 16.4.6 App Router, TypeScript, Tailwind CSS, Cloudflare Workers via OpenNext.
- D1 schema and migrations for identity, chapters, applications, application updates, memberships, status history, invitations, roles, audit, directory, events, volunteers, email, rate limits, and payment events.
- Better Auth identity with invitation-only activation, password recovery, email verification scaffold, and TOTP MFA.
- Central server-side policy with global/chapter/self scope and MFA-required administrative actions.
- Application queue, detail, approve/deny/request-information, applicant update links, and single-use invitations.
- Membership creation, chapter assignment, status history, dues status separate from membership standing.
- Member dashboard, profile/account settings, encrypted phone storage, notification preferences.
- Digital membership card with short-lived signed QR tokens and event check-in.
- Opt-in directory with field-level privacy controls.
- Admin event creation, public event pages, member registration, volunteer opportunities, volunteer registration.
- MFA enrollment, backup codes, and owner-assisted MFA reset.
- Password reset through Better Auth and the development email outbox.
- Turnstile server verification (requires configured site/secret keys), D1-backed form rate limiting.
- Stripe Checkout/Customer Portal/webhook code with live charging gated off.
- Unit, migration, Worker runtime, browser smoke, and full membership lifecycle E2E tests.

## Not implemented yet

- Real Stripe test-mode external execution. No Stripe test credentials are present; checkout is disabled.
- Real Resend delivery. Development uses an outbox; production requires `EMAIL_TRANSPORT=resend` and provider secrets.
- Turnstile widget/secret configuration. In production, forms fail closed when spam protection is not configured.
- CMS, CRM, facilities, documents, communications center, finance reporting, and system administration modules.
- Member role-assignment UI beyond the owner bootstrap; admin identity management remains a later milestone.
- Live payments, donations, production deployment, and DNS changes.

## Local requirements

- Node.js 22 or newer (Node 24 recommended).
- npm.

## Local setup

```powershell
npm install
Copy-Item .dev.vars.example .dev.vars
# Replace example values with local-only random secrets.
npm run db:verify
npm run bootstrap:owner
npm run build
npm run build:worker
npm run preview
```

`npm run bootstrap:owner` creates the single initial owner and global owner role. It prompts for email, name, and a hidden password, and refuses to run if an active owner exists. Add `--remote --env staging` only after the corresponding D1 database is provisioned and authorized.

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Next.js development server |
| `npm run build` | Next.js production build |
| `npm run build:worker` | OpenNext Cloudflare Worker build |
| `npm run preview` | Preview the built Worker locally |
| `npm run typecheck` | TypeScript check |
| `npm run lint` | ESLint |
| `npm test` | Vitest unit tests |
| `npm run db:generate` | Generate a Drizzle migration |
| `npm run db:migrate:local` | Apply migrations to local D1 |
| `npm run db:verify` | Apply local migrations and verify tables/triggers/seed |
| `npm run bootstrap:owner` | Create the initial owner |
| `npm run e2e:smoke` | Public form smoke test |
| `npm run e2e:membership` | Full membership lifecycle browser test |
| `npm run audit:prod` | Production dependency audit |

## Environment

Public configuration is documented in `.env.example`. Local Worker secrets belong in `.dev.vars`, which is ignored.

Required deployed secrets:

- `BETTER_AUTH_SECRET`
- `AUDIT_HASH_SALT`
- `PII_ENCRYPTION_KEY`
- `CARD_TOKEN_SECRET` (or auth secret fallback)
- `TURNSTILE_SECRET_KEY` / `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
- `EMAIL_TRANSPORT`, `RESEND_API_KEY`, `EMAIL_FROM`
- `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`

Safe payment defaults:

- `PAYMENTS_MODE=test`
- `PAYMENTS_LIVE_APPROVED=false`
- `DONATIONS_ENABLED=false`

## Testing

Start the Worker locally and run the browser tests:

```powershell
npm run build:worker
npm run preview
# In another terminal:
npm run e2e:smoke
npm run e2e:membership
```

For the full membership test, bootstrap the E2E owner first and provide a local-only test password through the environment:

```powershell
$env:E2E_OWNER_PASSWORD="<local-test-password>"
node scripts/bootstrap-owner.mjs --email=owner.e2e@example.com --name="E2E Owner" --password-env=E2E_OWNER_PASSWORD
```

The membership test covers application, request-information, approval, invitation, activation, sign-in, profile, directory, card, event registration, volunteer registration, check-in, member status management, password reset, MFA challenge, and honest billing status.

## Security rules

- No bearer tokens in browser storage; Better Auth cookies are HttpOnly and secure in production.
- Administrative authorization is server-side through `src/lib/policy/permissions.ts`.
- Chapter-scoped roles cannot access other chapters.
- Administrative mutations require MFA and fail closed without it.
- Applicant and member phone numbers are encrypted with AES-GCM.
- No card data is stored.
- Audit events are append-only and redact secrets/PII.
- Forms use honeypots, Turnstile (when configured), and D1-backed rate limiting.
- Development email outbox is disabled when `APP_ENV=production`.
- Production deployment, DNS changes, live payments, bulk email, and donations are not authorized.

## Repository rules

- Keep the application under `website/`.
- Do not modify DEFEND AI, Markets, Coder, Sports, SCS, or unrelated applications.
- Do not commit `.dev.vars`, `.wrangler/`, `.open-next/`, runtime databases, or secrets.
- Do not push or deploy without explicit owner authorization.
