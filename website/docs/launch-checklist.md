# Launch Checklist

**Current decision: NO-GO for public launch and NO-GO for production deployment.** Technical staging readiness is substantially complete; external integrations and legal readiness are not.

## Technical readiness

| Gate | Status | Evidence / remaining action |
|---|---|---|
| Staging baseline accepted | PASS | Worker version `084f2433` accepted as the Milestone 4 baseline; closeout version `1fd44e74` |
| Source control | PASS | Branch `rebuild/website-platform-v1`, draft PR #27 |
| CI verification | PASS | Typecheck, lint, unit tests, migrations, builds, production dependency scan |
| D1 migrations | PASS | Local verification: 56 tables, 2 audit triggers, Pasco seed |
| Membership/admin E2E | PASS | 33 checks after document/version/archive coverage is added |
| Newsletter subscribe/unsubscribe | PASS | Local encrypted-token flow and staging signup verified |
| Public accessibility | PASS | Axe WCAG 2.2 AA: 0 violations on 12 public routes |
| Authenticated accessibility | PASS | Axe: 0 violations on 15 admin and 7 member routes; mobile menu open verified |
| Mobile navigation | PASS | 390px: no overflow, 7 menu links, open/close verified |
| Security headers | PASS | CSP, nosniff, frame denial, referrer policy, permissions policy, COOP/CORP, no-store admin/member/auth |
| Auth fallback safety | PASS | Password forms use POST; no password query parameters on native fallback |
| Turnstile integration | PARTIAL | Test keys verified on staging; real production keys outstanding |
| Resend delivery | BLOCKED | No API key/domain/DNS verification |
| Stripe test mode | BLOCKED | No test keys/price/webhook secret |
| Analytics/search verification | BLOCKED | No Cloudflare/GSC/Bing tokens |
| Camera real-device test | BLOCKED | Requires owner phone; manual and automated fallback verified |
| Owner bootstrap/MFA on staging | BLOCKED | Requires owner-entered password |
| Cloudflare CI deployment | BLOCKED | Requires scoped API token and `ENABLE_STAGING_DEPLOY=true` |
| Encrypted D1 backup | PASS (local) | AES-256-GCM/scrypt backup and decrypt drill: 57 table definitions restored |
| Scheduled offsite backup | BLOCKED | Workflow prepared; requires `BACKUP_PASSPHRASE` and enable variable |
| R2 recovery | PASS | Object download/restore drill completed |
| Production account access | BLOCKED | Current account does not own `defend-network.org` |
| CSP nonce hardening | OPEN | Static CSP retains `'unsafe-inline'` for Next bootstrap; cache-safe nonce delivery unresolved |
| Manual screen-reader test | OPEN | Automated axe is clean; human NVDA/VoiceOver pass outstanding |
| Penetration test | OPEN | Not performed |
| Production rollback drill | PARTIAL | Worker version rollback and D1 Time Travel documented; production-scale drill not performed |

### Technical GO conditions

Technical GO requires all of the following:

1. Cloudflare CI token installed and a CI staging deployment succeeds.
2. Staging owner bootstrap and MFA verified with recovery codes stored offline.
3. Resend domain verified and one transactional email delivered.
4. Real Turnstile keys verified, including missing-token rejection.
5. Stripe test-mode checkout, failure, cancellation, duplicate webhook, and portal checks pass.
6. Analytics/search verification tokens verified.
7. Real-device camera scan and manual fallback pass.
8. Encrypted backup workflow produces a verified artifact; restore drill documented.
9. Production account/zone access confirmed without DNS changes.
10. Manual screen-reader pass and a security decision on the CSP residual.

## Legal and organizational readiness

| Gate | Status | Requirement |
|---|---|---|
| Entity / incorporation | NO-GO | Confirm legal entity and registered agent |
| 501(c)(3) / tax-exempt status | NO-GO | Counsel review; do not claim exempt status |
| Bylaws and membership criteria | NO-GO | Adopt and publish approved criteria |
| Privacy policy | NO-GO | Counsel-reviewed policy matching actual data flows |
| Terms of use | NO-GO | Counsel-reviewed terms |
| Florida charitable solicitation | NO-GO | Confirm registration/exception before solicitation |
| Youth safeguarding | NO-GO | Written policy, screening, reporting, and supervision |
| Insurance | NO-GO | Confirm general liability and related coverage |
| Payment/refund policy | NO-GO | Approve before any live dues |
| Data retention/deletion | NO-GO | Adopt schedule and member deletion process |
| Accessibility statement | NO-GO | Publish commitment and contact process |
| Donation readiness | NO-GO | Keep `DONATIONS_ENABLED=false` |
| Live subscription readiness | NO-GO | Keep `PAYMENTS_LIVE_APPROVED=false` |

## Explicit prohibitions until signed approval

- No merge to production.
- No production DNS or nameserver changes.
- No production Worker deployment.
- No live card charges.
- No charitable donation activation.
- No bulk email or newsletter blast.
- No claim that DEFEND is incorporated or tax-exempt.
- No real member identity documents in staging.

## Final sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Owner | | GO / NO-GO | |
| Technical lead | | GO / NO-GO | |
| Legal counsel | | GO / NO-GO | |

**Overall launch decision: NO-GO.**
