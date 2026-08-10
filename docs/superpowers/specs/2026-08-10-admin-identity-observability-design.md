<!-- DEFEND-AI-INGEST: EXCLUDE -->

# DEFEND Admin Identity and Observability Design

**Date:** 2026-08-10
**Status:** Approved

## Objective

Upgrade the DEFEND Admin Workstation with a more visible admin background and a secure identity-administration system. The workstation will distinguish registered accounts from anonymous visitors, support administrator-created accounts and email invitations, expose searchable visitor/session telemetry, and audit sensitive access.

Public self-registration and the end-user account interface are outside this implementation. This phase creates the identity foundation, administrator workflows, activation flow, and account login/session backend needed for later public-facing account features.

## Existing deployment

DEFEND runs on a Windows machine and is exposed through Cloudflare Tunnel:

- `https://ai.defend-network.org` routes to Next.js at `127.0.0.1:3000`.
- `https://api.defend-network.org` routes to FastAPI at `127.0.0.1:8000`.
- Persistent application data remains in the configured DEFEND data directory, currently based on `C:\DEFEND_DATA`.

Invitation URLs use the public `https://ai.defend-network.org` origin. Gmail SMTP sends invitations from `chairman@defend-network.org`. SMTP credentials and the public base URL are deployment environment variables and are never committed.

## Architecture

### Identity storage

Add a dedicated SQLite identity store, `identity.db`, separate from the existing `visitors.db`. The identity store owns:

- accounts and roles;
- password hashes;
- account sessions;
- invitation lifecycle records;
- account-to-visitor links;
- login and activation events; and
- immutable administrative audit events.

The visitor store continues to own pseudonymous visitors, visitor sessions, conversation indexes, usage events, device metadata, and connection history. Explicit account-to-visitor links connect the two domains without making a device fingerprint the primary account identity.

### Application boundaries

- `IdentityStore` encapsulates the identity schema, migrations, transactions, and queries.
- FastAPI identity and owner/admin routes enforce authorization, validate inputs, execute account/invitation actions, and expose bounded search/detail queries.
- The Admin Workstation consumes typed identity APIs for Accounts, Visitors, Invitations, and detail views.
- An email adapter sends activation invitations through Gmail SMTP and reports delivery outcomes without exposing credentials.
- A retention task removes expired detailed connection records.

Each unit has a narrow interface so storage, email, authorization, and presentation can be tested independently.

## Roles and authorization

The roles are `owner`, `admin`, and `user`.

- The existing environment-configured owner bootstraps the single owner record in `identity.db`.
- No UI or API operation can create or promote another owner.
- Admins may create, invite, view, edit, and disable end-user accounts.
- Only the owner may create administrators or promote, disable, or demote administrator accounts.
- Admins cannot change their own role or use account-management APIs to obtain owner privileges.
- Admins may disable end-user accounts, immediately blocking future access.
- Only the owner may anonymize or permanently delete accounts.
- Admins and the owner may view visitor telemetry and conversation content. Every sensitive content or telemetry view creates an audit event.

These rules are enforced server-side. UI visibility is only a convenience and is not the authorization boundary.

## Account and invitation lifecycle

### Account creation

An authorized administrator supplies at least a display name, normalized email address, and intended role. The new account begins in `pending_activation` state. Duplicate normalized emails are rejected.

### Invitation creation and delivery

DEFEND generates a cryptographically random invitation token. Only a one-way hash of the token is stored. The invitation:

- is single-use;
- expires 48 hours after creation;
- can be revoked;
- records its creator, intended role, creation and expiration timestamps, delivery state, consumption state, and delivery error when applicable; and
- is emailed from `chairman@defend-network.org` through Gmail SMTP.

The invitation URL opens an activation page on `ai.defend-network.org`. The Admin Workstation also exposes the copyable link as a fallback. If email delivery fails, the account remains pending, the failure is visible, and the link remains available for manual delivery. Regenerating or resending an invitation invalidates the prior unconsumed token.

### Activation

The recipient opens the invitation, chooses a password, and submits it to FastAPI. The API validates the token hash, expiry, revocation state, consumption state, intended account, and password policy in one transaction. Success stores the password hash, consumes the invitation, activates the account, and records an activation event.

### Login and sessions

Passwords use a modern slow password hash. Successful login creates a cryptographically random session identifier delivered in a secure, HTTP-only, same-site cookie. Only a hash of the identifier is stored. Sessions have explicit creation, last-seen, expiration, and revocation timestamps.

Raw passwords, invitation tokens, authentication cookies, and reusable session tokens are never logged or stored in reusable form. Disabled accounts cannot create or continue sessions.

Public self-registration is not included. A public account-management interface beyond activation is deferred to a later project.

## Visitor, device, and connection telemetry

The existing server-assigned visitor and visitor-session IDs remain authoritative for anonymous traffic. DEFEND records:

- visitor and visitor-session identifiers;
- full IP-address history;
- user agent, browser, platform, device type, and language;
- a keyed hash of the device fingerprint;
- keyed hashes of cookie/session identifiers;
- first seen, last seen, session duration, and seen count;
- conversations and usage activity; and
- an account association established by authenticated use.

DEFEND never stores raw authentication cookies or reusable session tokens. Device fingerprints assist investigation but never automatically prove that two visitors are the same person.

When an authenticated account uses DEFEND, the current server-issued visitor identity may be linked to the account. One account may link to multiple visitors and devices. Anonymous records remain pseudonymous until authenticated activity creates an explicit link.

Full IP history and detailed connection telemetry expire after 90 days. The cleanup process deletes or aggregates only the expiring detailed records; durable account audit facts such as creation, disabling, role changes, and last-access time remain.

Client IP resolution trusts Cloudflare forwarding headers only when the existing trusted-Cloudflare deployment setting is enabled and the request path satisfies the configured proxy trust rules. Otherwise the direct peer address is used.

## Admin Workstation experience

### Visual treatment

The admin and owner pages use the approved **Prominent** background treatment. The overlay is reduced enough that `admin-bg.jpg` is clearly recognizable. Navigation, cards, tables, inputs, and modal surfaces retain darker translucent backgrounds and accessible contrast.

### Users & Roles workspace

Replace the current placeholder with the approved top-tab layout:

1. **Accounts**
2. **Visitors**
3. **Invitations**

A consistent toolbar provides search, filters, pagination, refresh, and context-sensitive actions.

### Accounts tab

Search by display name, email, account ID, role, and status. The list shows account identity, role, activation status, created date, last access, recent IP, device count, and active-session count.

The detail view includes:

- account identity and state;
- linked visitor/device records;
- login and activation history;
- active and historical sessions;
- recent IP history;
- conversations and usage activity;
- invitation history; and
- actions allowed for the current administrator's role.

### Visitors tab

Search by visitor ID, IP address, browser, platform, device type, language, fingerprint hash, and linked account. The list shows first seen, last seen, seen count, session count, device summary, recent IP, activity totals, and account association.

The detail view includes session and IP timelines, client metadata, conversations, usage events, linked account information, and audited access to conversation content.

### Invitations tab

Search by recipient, creator, intended role, and status. Show creation and expiration times, delivery outcome, and whether an invitation is pending, consumed, expired, or revoked. Authorized actions include copy link, resend, revoke, and regenerate.

## Audit model

Sensitive reads and all administrative writes create append-only audit events. Each event records:

- acting administrator account;
- action type;
- target type and identifier;
- timestamp;
- success or failure outcome;
- request identifier and relevant client context; and
- bounded metadata that excludes secrets, raw passwords, raw tokens, and raw authentication cookies.

Audited actions include account creation and updates, disabling, anonymization/deletion, role changes, invitation operations, visitor/detail inspection, raw IP-history access, session inspection, and conversation-content viewing.

## Error handling and operational behavior

- Account, invitation, activation, role, and deletion operations use transactions.
- API errors are structured and safe to display without leaking secrets.
- Login and activation errors are generic enough to prevent account enumeration.
- Login and activation endpoints are rate-limited.
- Email delivery failure does not activate an account or silently discard its invitation.
- Expired or consumed invitations return explicit non-sensitive states and cannot be reused.
- Searches are paginated and bounded; detail endpoints cap nested history sizes.
- Retention cleanup is idempotent and records its result without logging retained sensitive values.
- Missing Gmail configuration prevents email delivery but does not prevent an authorized administrator from generating a copyable invitation.

## Configuration

Deployment configuration uses environment variables. Exact names will be finalized in the implementation plan, covering:

- identity database/data-root location;
- public web origin;
- Gmail SMTP host, port, username, app password, and sender;
- account-session lifetime;
- invitation lifetime fixed by this design at 48 hours;
- connection-detail retention fixed by this design at 90 days; and
- Cloudflare proxy trust behavior.

No secret values belong in GitHub, `.env` files committed to Git, logs, audit metadata, or frontend bundles.

## Testing and verification

### Storage and authorization tests

- schema creation and migration;
- normalized-email uniqueness;
- owner bootstrap idempotence;
- role matrix and privilege-escalation attempts;
- administrator self-role restrictions;
- disable, anonymize, and delete boundaries; and
- transactional rollback on failure.

### Invitation and authentication tests

- create, email, copy, resend, regenerate, revoke, expire, consume, and reuse attempts;
- email-delivery failure behavior;
- password hashing and policy validation;
- activation races and duplicate submissions;
- login, logout, expiry, revocation, and disabled-account behavior;
- session-cookie attributes; and
- rate limiting and account-enumeration resistance.

### Telemetry and audit tests

- anonymous visitor/session creation;
- IP and client-metadata capture;
- trusted Cloudflare header handling;
- account-to-visitor linking across multiple devices;
- search and pagination;
- 90-day retention cleanup; and
- audit creation for sensitive reads and administrative writes.

### UI and regression verification

- Accounts, Visitors, and Invitations states and actions;
- role-gated controls;
- search, filters, pagination, loading, empty, and error states;
- responsive layout and Prominent background contrast;
- activation page behavior;
- existing chat, research, visitor, and admin workflows;
- Python automated tests and syntax compilation; and
- Next.js production build and type checking.

## Implementation boundaries

The implementation should be split into independently testable units:

1. identity schema and store;
2. bootstrap owner and role authorization;
3. invitations, Gmail adapter, activation, and sessions;
4. visitor IP/client-history extensions and retention;
5. account-to-visitor linking and audit events;
6. owner/admin APIs;
7. activation UI;
8. Admin Workstation Accounts, Visitors, and Invitations UI; and
9. visual background update and regression verification.

The implementation must not add public self-registration, additional owners, raw authentication-cookie storage, fingerprint-based automatic identity merging, or unrelated refactoring.
