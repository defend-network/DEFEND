# Security

## Implemented controls

- Better Auth sessions with HttpOnly cookies and secure-cookie mode controlled by `APP_ENV=production`.
- No bearer tokens in browser storage.
- Server-side `ActorContext` loaded from Better Auth session plus active `role_assignments`.
- Central `can()` policy with global, chapter, and self scope.
- MFA-required permissions fail closed when MFA is not verified.
- Invitation tokens are random, prefixed, hashed with SHA-256 before storage, expiring, revocable, and single-use.
- Applicant phone numbers are encrypted with AES-GCM using `PII_ENCRYPTION_KEY`.
- Audit events are append-only at the database level; update/delete triggers reject mutation.
- Audit metadata redacts passwords, tokens, cookies, authorization values, card data, phone, address, email, and notes.
- Contact IP values are hashed with `AUDIT_HASH_SALT`; raw IPs are not stored in audit events.
- Security headers: HSTS in production, CSP baseline, nosniff, frame denial, referrer policy, and permissions policy.
- Public forms use a honeypot field, server-side Zod validation, duplicate application checks, and bounded field sizes.
- D1 queries are parameterized through Drizzle.

## Known gaps

- MFA enrollment and recovery UI are not implemented. Administrative mutations that require MFA are intentionally blocked.
- Turnstile is not yet wired into public forms. Server-side rate limiting is not yet implemented beyond Better Auth's database-backed auth limits and the form honeypot.
- The CSP uses `'unsafe-inline'` for Next.js bootstrap scripts. Nonce-based CSP hardening is pending.
- Password reset and invitation email delivery are not configured. No fake success is shown.
- File upload/document authorization is schema-ready but not implemented.
- No production secret management has been performed.
- No penetration test has been performed.

## Production requirements

Before production:

- Enforce MFA enrollment for owner, national admin, chapter admin, and staff.
- Add Turnstile and product-level rate limiting.
- Replace the baseline CSP with a nonce/hash-based policy.
- Configure email delivery, SPF, DKIM, DMARC, and bounce handling.
- Verify all authorization matrix tests and IDOR tests.
- Add backup/restore and rollback drills.
- Complete legal review of privacy, terms, membership criteria, and organizational status copy.
- Do not enable live payments or donations until legal, financial, processor, and owner readiness are confirmed.
