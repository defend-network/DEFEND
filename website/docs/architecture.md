# Architecture

## Overview

The DEFEND website is an isolated Next.js application deployed to Cloudflare Workers with the OpenNext adapter.

```text
Browser
  ↓
Cloudflare edge
  ↓
Next.js Worker (OpenNext)
  ├── Public pages (static + server-rendered)
  ├── Auth routes (Better Auth)
  ├── Member portal
  ├── Admin workstation
  └── Route handlers and server actions
        ↓
       D1
```

R2 bindings are defined for future private documents and public media. D1 is the canonical relational store.

## Why this stack

- Next.js provides server components, server actions, metadata, routing, and a single application boundary for public and authenticated surfaces.
- Cloudflare Workers provides a low-cost global deployment target compatible with the organization's hosting preference.
- D1 provides SQL persistence with migrations and atomic batches. It is sufficient for the expected launch scale.
- Better Auth provides the canonical identity and session substrate without a separate identity vendor.
- Central policy code owns authorization. UI state is never treated as authorization.

## Boundaries

- `src/app/(public)` — public website.
- `src/app/(auth)` — login, activation, password reset.
- `src/app/members` — member portal.
- `src/app/admin` — administrative workstation.
- `src/app/api` — auth, health, and invitation routes.
- `src/lib/auth` — Better Auth configuration, client, session, invitations.
- `src/lib/policy` — permission vocabulary and server-side actor policy.
- `src/lib/audit` — append-only audit writes and redaction.
- `src/lib/db` — D1/Drizzle access.
- `src/lib/security` — encrypted PII handling.
- `src/db/schema` — Drizzle schema.
- `migrations` — forward-only SQL migrations.

## Roles and scope

Roles: owner, national_admin, chapter_admin, staff, volunteer_coordinator, member.

Scope types:

- `global` — organization-wide.
- `chapter` — one chapter only.
- `self` — the actor's own record.

`can(actor, permission, resource)` is the authorization entry point. Chapter-scoped permissions require a matching `chapterId`. Client filters may narrow scope but never widen it.

## Identity flow

```text
Manual application review
    ↓
Approved applicant
    ↓
Invitation token (hashed, expiring)
    ↓
Activation page sets password
    ↓
Better Auth user + credential account
    ↓
Member portal
```

No public self-signup is enabled. Invitation tokens are stored hashed and never placed in server logs. Activation is server-side and single-use.

## Data model

Core tables:

- Better Auth: `user`, `session`, `account`, `verification`, `two_factor`, `rate_limit`.
- Organization: `chapters`, `member_profiles`, `memberships`, `membership_status_history`.
- Applications: `membership_applications`, `application_reviews`, `application_update_tokens`.
- Payments: `membership_subscriptions`, `payment_events`.
- Access: `invitations`, `role_assignments`.
- Audit: `admin_audit_events`.
- Directory: `directory_profiles`.
- Contact: `contact_messages`.
- Email: `email_outbox`, `email_delivery_events`.
- Events: `events`, `event_registrations`, `event_checkins`.
- Volunteer: `volunteer_opportunities`, `volunteer_registrations`.
- Abuse controls: `request_rate_limits`.

Pasco County is seeded as `in_development`. Planned chapters are content-only and cannot be selected for membership assignment.

## Membership lifecycle

```text
Application submitted
  → admin review
  → approve / deny / request information
  → applicant update link (request-information path)
  → approval creates single-use invitation
  → activation creates Better Auth user, member profile, membership, and status history
  → founding_access while live billing is disabled
  → Stripe test/live billing later when authorized
```

`founding_access` is not the same as paid. `dues_status` is tracked separately from membership standing. A member is not marked paid unless a verified payment event or an authorized owner action records it.

## MFA and recovery

Administrative permissions that mutate protected data require TOTP MFA. A session is treated as MFA-verified only when the user has `twoFactorEnabled` set by Better Auth. Owner-assisted reset deletes the target TOTP record, clears `twoFactorEnabled`, revokes sessions, and writes an audit event.

## Email and payments

- Email uses Resend when configured; otherwise a development outbox stores local-only emails. The outbox route is unavailable in production.
- Stripe Checkout, Customer Portal, and webhooks are implemented. Live charging is gated by `PAYMENTS_MODE` and `PAYMENTS_LIVE_APPROVED`.
- Webhook events are stored by unique Stripe event ID before processing to make retries idempotent.


## D1 constraints

D1 has no interactive transactions across requests. Use:

- atomic `batch()` for dependent writes;
- guarded updates with expected status;
- unique idempotency keys for webhook events;
- compensation for multi-service operations where necessary.

If usage approaches D1 limits, migrate the portable SQL schema to Postgres/Hyperdrive.

## Deployment shape

- Local: `next dev` or `wrangler dev` with local D1/R2.
- Staging: separate Worker, D1, R2, secrets, and Stripe test mode.
- Production: separate Worker, D1, R2, secrets, and live payments only after authorization.

The current milestone does not deploy staging or production.
