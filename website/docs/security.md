# Security

## Implemented controls

- Better Auth sessions with HttpOnly cookies and secure-cookie mode controlled by `APP_ENV=production`.
- No bearer tokens in browser storage.
- Server-side `ActorContext` loaded from Better Auth session plus active `role_assignments`.
- Central `can()` policy with global, chapter, and self scope.
- MFA-required permissions fail closed when MFA is not verified.
- TOTP enrollment, backup codes, and owner-assisted reset that revokes sessions and writes an audit event.
- Invitation and applicant-update tokens are random, hashed with SHA-256 before storage, expiring, revocable, and single-use.
- Applicant/member phone numbers are encrypted with AES-GCM using `PII_ENCRYPTION_KEY`.
- Digital card QR tokens are HMAC-signed, short-lived, and contain no personal information.
- Audit events are append-only at the database level; update/delete triggers reject mutation.
- Audit metadata redacts passwords, tokens, cookies, authorization values, card data, phone, address, email, and notes.
- Client IP values are hashed with `AUDIT_HASH_SALT`; raw IPs are not stored in audit events.
- Security headers: HSTS in production, CSP baseline, nosniff, frame denial, referrer policy, permissions policy.
- Public forms use honeypots, server-side Zod validation, optional Turnstile verification, duplicate application checks, and D1-backed rate limiting.
- Newsletter unsubscribe links use HMAC-signed tokens, a confirmation POST, masked email display, and audit logging.
- Admin/member/auth responses use private no-store caching; authenticated pages and APIs are excluded from shared caches.
- D1 backups are AES-256-GCM encrypted with scrypt-derived keys and verified by checksum before restore.
- Authenticated accessibility audit covers admin and member routes at desktop and mobile navigation.
- Production fails closed when Turnstile is not configured.
- D1 queries are parameterized through Drizzle.
- Stripe webhooks verify signatures, store unique event IDs, and treat duplicate deliveries as no-ops.
- Live payment activation is gated by explicit flags.

## Known gaps

- Staging uses Cloudflare Turnstile test keys (public test site key plus test secret). Local development runs without Turnstile. Production requires real Turnstile site/secret keys.
- The development email outbox is enabled only outside production. Real Resend delivery has not been externally verified.
- Stripe Checkout and Customer Portal have not been executed against an external Stripe test account because no test credentials are present. Webhook signature/idempotency logic was locally tested.
- CSP is a static header with `'unsafe-inline'` for Next.js bootstrap scripts. A nonce-based policy was tested but removed after cached HTML/nonce mismatches broke hydration. This remains a documented production security decision: either accept the residual XSS surface or implement cache-safe nonce/hash delivery before launch.
- MFA recovery is implemented but not exercised end-to-end with two independent administrators.
- Email verification is implemented but invitation activation marks invited addresses verified; the resend verification path was not exercised end-to-end.
- Email OTP sign-in is implemented with a hashed, short-lived, attempt-limited code and the development outbox. Real Resend delivery has not been externally verified.
- Session-level MFA is tracked with `session.mfa_verified_at`. Email-only sessions are not treated as MFA-verified for sensitive administrative actions.
- Authenticator recovery codes are displayed only after successful enrollment verification. An exposed pending TOTP enrollment and its recovery codes were invalidated on the dedicated DEFEND staging owner account on 2026-11-23; the owner must re-enroll a fresh authenticator.
- SMS verification is not configured. No SMS provider is active and no SMS messages are sent.
- Passkeys are not available in this build; no passkey plugin is installed.
- Document uploads are admin-only with MIME/size validation, private R2 storage, authorized downloads, inline authorized preview, version history/restoration, and download audit. Archive is implemented without deleting the original R2 object.
- Scheduled offsite backups remain disabled until owner secrets and the enable variable are configured.
- No production secret management has been performed.
- No penetration test has been performed.

## Staging

Staging uses separate Worker, D1, and R2 resources at `https://defend-website-staging.owner-e75.workers.dev`. Staging uses the development email outbox and test-mode/disabled payments. No production DNS was changed. Automated staging deployment is prepared but requires a Cloudflare API token in GitHub Actions.

## Production requirements

Before production:

- Configure Turnstile, Resend, Stripe test keys, and DNS authentication records.
- Enforce MFA enrollment for owner, national admin, chapter admin, and staff.
- Replace the baseline CSP with a nonce/hash-based policy.
- Exercise Stripe test-mode checkout, renewal, failure, cancellation, refund, and duplicate webhooks.
- Verify email verification and recovery with real delivery.
- Run the full authorization matrix and IDOR tests.
- Verify encrypted backups and restore drills; enable the scheduled workflow.
- Complete legal review of privacy, terms, membership criteria, and organizational status copy.
- Do not enable live payments or donations until legal, financial, processor, and owner readiness are confirmed.
