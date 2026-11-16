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
- Production fails closed when Turnstile is not configured.
- D1 queries are parameterized through Drizzle.
- Stripe webhooks verify signatures, store unique event IDs, and treat duplicate deliveries as no-ops.
- Live payment activation is gated by explicit flags.

## Known gaps

- Turnstile site/secret keys are not configured in this environment. The widget is inactive locally; production requires configuration.
- The development email outbox is enabled only outside production. Real Resend delivery has not been externally verified.
- Stripe Checkout and Customer Portal have not been executed against an external Stripe test account because no test credentials are present. Webhook signature/idempotency logic was locally tested.
- CSP uses `'unsafe-inline'` for Next.js bootstrap scripts. Nonce-based hardening is pending.
- MFA recovery is implemented but not exercised end-to-end with two independent administrators.
- Email verification is implemented but invitation activation marks invited addresses verified; the resend verification path was not exercised end-to-end.
- File upload/document authorization is schema-ready but not implemented.
- CMS/CRM/facilities/finance modules are not implemented.
- No production secret management has been performed.
- No penetration test has been performed.

## Production requirements

Before production:

- Configure Turnstile, Resend, Stripe test keys, and DNS authentication records.
- Enforce MFA enrollment for owner, national admin, chapter admin, and staff.
- Replace the baseline CSP with a nonce/hash-based policy.
- Exercise Stripe test-mode checkout, renewal, failure, cancellation, refund, and duplicate webhooks.
- Verify email verification and recovery with real delivery.
- Run the full authorization matrix and IDOR tests.
- Add backup/restore and rollback drills.
- Complete legal review of privacy, terms, membership criteria, and organizational status copy.
- Do not enable live payments or donations until legal, financial, processor, and owner readiness are confirmed.
