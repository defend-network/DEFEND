# DEFEND Website

Isolated organizational website, member portal, and administrative workstation for DEFEND.

**Branch:** `rebuild/website-platform-v1`

**Status:** Foundation implemented. This is not a production release.

## What is implemented

- Next.js 16.4.6 App Router application with TypeScript and Tailwind CSS.
- Cloudflare Workers configuration through the OpenNext adapter.
- D1 database schema and migrations for identity, chapters, applications, memberships, invitations, roles, audit, directory, contact messages, and payment events.
- Better Auth identity with invitation-only account activation.
- Central server-side role policy with chapter scoping and MFA-required administrative actions.
- Append-only administrative audit table with redaction helpers.
- Public layout, navigation, homepage, About, Programs, Chapters, Membership, Apply, and Contact pages.
- Real application and contact form persistence with validation and encrypted phone storage.
- Protected member dashboard shell and read-only administrative overview.
- Vitest unit tests, migration verification, Worker runtime smoke checks, and a Playwright smoke script.

## What is not implemented yet

- Application review/approve/deny decisions and invitation-creation UI.
- Member profile editing, digital card, directory, events, and billing UI.
- CRM, facilities, documents, CMS, communications, finance, and system modules.
- Email delivery. Password reset and invitation email are not configured.
- MFA enrollment UI. The Better Auth two-factor plugin and schema are configured, but administrative mutations that require MFA fail closed until enrollment is implemented.
- Turnstile UI and server verification.
- Stripe checkout/webhooks. Live payments and donations are disabled.
- Production deployment. Not authorized.

## Local requirements

- Node.js 22 or newer (Node 24 recommended).
- npm.
- A Cloudflare account for future staging/production deployment. No remote resources are created by the default commands.

## Local setup

```powershell
npm install
Copy-Item .dev.vars.example .dev.vars
# Replace the example secrets with local-only random values.
npm run db:verify
npm run bootstrap:owner
npm run build
npm run build:worker
npm run preview
```

`npm run preview` starts the built Worker locally with Wrangler. Local D1 data lives under `.wrangler/` and is ignored by Git.

`npm run bootstrap:owner` creates the single initial owner account and global owner role. It prompts for the email, display name, and a hidden password. It refuses to run if an active owner already exists. Use `--remote --env staging` only after the corresponding D1 database is provisioned and authorized. Never pass the password on the command line or store it in Git.

`npm run dev` starts the Next.js development server. OpenNext's development integration supplies local Cloudflare bindings when available.

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
| `npm run db:generate` | Generate a Drizzle migration from schema changes |
| `npm run db:migrate:local` | Apply migrations to local D1 |
| `npm run db:verify` | Apply local migrations and verify tables, triggers, and seed data |
| `npm run bootstrap:owner` | Create the single initial owner account and global owner role |
| `npm run e2e:smoke` | Playwright smoke test against a running Worker |
| `npm run audit:prod` | Production dependency audit |

## Environment

Public configuration is documented in `.env.example`. Local Worker secrets belong in `.dev.vars`, which is ignored.

Required deployed secrets:

- `BETTER_AUTH_SECRET` — high-entropy signing secret.
- `AUDIT_HASH_SALT` — salt for hashed client IP audit context.
- `PII_ENCRYPTION_KEY` — key material for encrypted applicant phone numbers.

Feature flags default to safe values:

- `PAYMENTS_MODE=test`
- `PAYMENTS_LIVE_APPROVED=false`
- `DONATIONS_ENABLED=false`

## Cloudflare configuration

`wrangler.jsonc` defines:

- D1 binding: `DB`
- R2 bindings: `DOCUMENTS` and `MEDIA`
- Static assets binding: `ASSETS`
- Compatibility date and `nodejs_compat`

The D1 `database_id` is a placeholder. Replace it only when a development or staging D1 database is provisioned with owner approval. Do not deploy production from this branch without a separate release authorization.

## Database

- Schema: `src/db/schema/`
- Migrations: `migrations/`
- Local data: `.wrangler/state/v3/d1/`
- Pasco County is seeded as `in_development`. Do not change that status without verified evidence.

The audit table has database triggers that reject updates and deletes.

## Security notes

- No bearer tokens in browser storage. Sessions use Better Auth cookies.
- Administrative authorization is enforced server-side through `src/lib/policy/permissions.ts`.
- Chapter-scoped roles cannot access other chapters.
- Administrative mutations that require MFA are denied when MFA is not verified.
- Applicant phone numbers are encrypted with AES-GCM.
- No card data is stored.
- Contact and application forms use honeypot spam protection. Turnstile is pending.
- The CSP is a baseline; nonce-based hardening is pending.
- Production deployment, DNS changes, live payments, bulk email, and real donations are not authorized from this milestone.

## Documentation

- `docs/architecture.md`
- `docs/security.md`
- `docs/deployment.md`

## Repository rules

- Keep the application under `website/`.
- Do not modify DEFEND AI, Markets, Coder, Sports, SCS, or unrelated applications.
- Do not commit `.dev.vars`, `.wrangler/`, `.open-next/`, runtime databases, or secrets.
- Do not push or deploy without explicit owner authorization.
