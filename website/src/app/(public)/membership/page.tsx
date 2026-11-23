import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { siteConfig } from "@/lib/config/site";
import {
  listTierCatalog,
  type TierCatalogEntry,
} from "@/lib/membership/tiers";

export const metadata: Metadata = {
  title: "Membership",
  description:
    "DEFEND membership tiers: Free, Standard, Supporter, and Patron. Application review, member portal access, and program eligibility.",
};

export const dynamic = "force-dynamic";

const faqs = [
  {
    question: "Is membership open now?",
    answer:
      "Yes. Applications are being accepted for the Pasco County founding chapter. Every paid membership application is reviewed manually.",
  },
  {
    question: "Who can apply?",
    answer:
      "General membership is open to adults who support DEFEND's lawful mission, regardless of sex. Family participation and specific programs are optional and may have their own lawful eligibility, capacity, and fee rules. Youth-related features remain disabled until safeguarding requirements are approved.",
  },
  {
    question: "What does membership cost?",
    answer:
      "Membership has Free, Standard, Supporter, and Patron tiers. Current monthly and annual amounts are shown in the membership tiers section. Online billing is not active yet.",
  },
  {
    question: "Can I join before paying?",
    answer:
      "Free accounts activate after email verification. Approved paid applicants can activate an account and access eligible member features before live billing is enabled. Membership standing and payment status are tracked separately.",
  },
  {
    question: "Can I upgrade a Free account?",
    answer:
      "Free members can apply for a paid tier. The platform will not create a second account for the same email address. Upgrade payment activation is still being completed, so contact DEFEND if you need assistance in the meantime.",
  },
  {
    question: "What can Free members access?",
    answer:
      "Free accounts can view announcements and register for eligible public events. Workshops, gym access, volunteering, and the business directory require Standard membership or higher, subject to policy and capacity.",
  },
  {
    question: "Is DEFEND a 501(c)(3) or 501(c)(7)?",
    answer:
      "Neither status has been recognized. DEFEND is not yet incorporated. Initial legal planning prioritizes a qualifying 501(c)(3) structure; a separate 501(c)(7) may be evaluated later.",
  },
  {
    question: "Are donations tax-deductible?",
    answer:
      "No. DEFEND is not currently soliciting charitable donations and does not represent contributions as tax-deductible.",
  },
];

function money(cents: number | null): string {
  if (cents == null) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function monthlyLabel(tier: TierCatalogEntry): string {
  if (tier.allowsCustomAmount) {
    return `From ${money(tier.minimumMonthlyCents)}`;
  }
  return money(tier.monthlyCents);
}

function annualLabel(tier: TierCatalogEntry): string {
  return `${tier.allowsCustomAmount ? "From " : ""}${money(tier.annualCents)}`;
}

function tierAccess(tier: TierCatalogEntry): string {
  if (tier.key === "free") {
    return "Announcements and eligible public events.";
  }
  if (tier.key === "standard") {
    return "Workshops, gym eligibility, volunteering, and the member directory.";
  }
  if (tier.key === "supporter") {
    return "Standard access plus configurable Supporter benefits.";
  }
  return "Standard and Supporter access plus configurable Patron benefits.";
}

export default async function MembershipPage() {
  let tiers: TierCatalogEntry[] = [];
  let catalogError = false;
  try {
    tiers = await listTierCatalog();
  } catch {
    catalogError = true;
  }

  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Membership</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Membership tiers built around participation, support, and community.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              Start with a Free account or apply for paid membership. Paid
              applications are reviewed by a person, and no subscription begins
              without explicit authorization.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container>
          <SectionHeading
            eyebrow="Membership tiers"
            title="Choose the level that fits your participation."
            description="Current amounts come from the effective-dated membership catalog. Online billing is not active yet."
          />

          {catalogError ? (
            <Alert tone="warning" className="mt-8">
              The membership catalog is temporarily unavailable. Contact DEFEND
              for current pricing before applying.
            </Alert>
          ) : tiers.length === 0 ? (
            <Alert tone="warning" className="mt-8">
              Membership pricing is being configured. Contact DEFEND for current
              details.
            </Alert>
          ) : (
            <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {tiers.map((tier) => (
                <Card
                  key={tier.key}
                  className={
                    tier.key === "standard"
                      ? "border-navy-800/30 shadow-[0_18px_50px_-30px_rgba(16,31,56,0.55)]"
                      : ""
                  }
                >
                  <CardHeader>
                    <div className="flex items-center justify-between gap-2">
                      <Eyebrow>{tier.name}</Eyebrow>
                      {tier.key === "standard" ? (
                        <Badge variant="green">Core</Badge>
                      ) : null}
                    </div>
                    <p className="mt-2 text-3xl font-semibold text-navy-900">
                      {monthlyLabel(tier)}
                      <span className="text-sm font-normal text-slate-500">
                        {" "}
                        / month
                      </span>
                    </p>
                    <p className="text-sm text-slate-500">
                      {annualLabel(tier)} / year
                    </p>
                    <p className="text-sm leading-6 text-slate-600">
                      {tier.description}
                    </p>
                  </CardHeader>
                  <CardContent className="grid gap-4">
                    <p className="text-sm leading-6 text-slate-700">
                      {tierAccess(tier)}
                    </p>
                    {tier.key === "free" ? (
                      <Button asChild variant="secondary" className="w-full">
                        <Link href="/register">Create free account</Link>
                      </Button>
                    ) : (
                      <Button
                        asChild
                        variant={tier.key === "standard" ? "primary" : "secondary"}
                        className="w-full"
                      >
                        <Link href={`/apply?tier=${tier.key}`}>
                          Apply for {tier.name}
                        </Link>
                      </Button>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          <p className="mt-6 text-sm leading-6 text-slate-500">
            Patron members choose a recurring amount at or above the published
            minimum. The selected amount is confirmed before any subscription is
            created or changed. Annual amounts reflect the approved 10% discount.
          </p>
        </Container>
      </section>

      <section className="border-y border-slate-200 bg-white py-16 sm:py-20">
        <Container className="grid gap-12 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <SectionHeading
              eyebrow="What membership includes"
              title="Access is tied to the approved tier, not to assumptions."
              description="Items that are not yet operating remain labeled accordingly."
            />
            <ul className="mt-8 grid gap-4 text-sm leading-6 text-slate-700">
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Participation in the Pasco County founding chapter as it develops.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Access to the member portal, profile, and chapter information for
                approved paid members.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Eligibility for workshops and volunteer opportunities at Standard
                membership or higher.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Gym eligibility at Standard membership or higher, subject to
                facility readiness, safety onboarding, and waivers.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Opt-in member directory visibility, controlled by the member.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                A digital membership card once the member portal is active.
              </li>
            </ul>
            <Alert tone="info" className="mt-8">
              Tier benefits are configurable. No exclusive patron listing or
              invented benefit is being offered. Any new benefit will be
              published with its actual availability.
            </Alert>
          </div>

          <aside className="space-y-4">
            <Card className="border-navy-800/10 bg-navy-900 text-white">
              <CardHeader>
                <Eyebrow className="text-[#f0a0aa]">Membership vs. payment</Eyebrow>
                <CardTitle className="text-white">
                  Standing and payment are separate.
                </CardTitle>
                <p className="text-sm leading-6 text-slate-300">
                  Membership standing is recorded separately from payment status.
                  Approved members may access eligible portal features before live
                  billing is activated. No real charge is collected until legal,
                  financial, processor, and owner readiness are confirmed.
                </p>
              </CardHeader>
              <CardContent>
                <Button asChild className="w-full">
                  <Link href="/apply">Apply for paid membership</Link>
                </Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Organizational status</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  {siteConfig.status.legal} {siteConfig.status.billing}
                </p>
              </CardContent>
            </Card>
          </aside>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container>
          <SectionHeading
            eyebrow="How it works"
            title="Register, apply, review, activate."
            description="Free accounts are self-service. Paid memberships begin with an application and manual review."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-4">
            {[
              [
                "01",
                "Register",
                "Create a Free account with email verification, or apply for a paid tier.",
              ],
              [
                "02",
                "Review",
                "An administrator reviews each paid application and records a decision.",
              ],
              [
                "03",
                "Activate",
                "Approved applicants receive an invitation to activate their account.",
              ],
              [
                "04",
                "Authorize",
                "When live billing is approved, members explicitly authorize the selected subscription.",
              ],
            ].map(([number, title, body]) => (
              <Card key={title}>
                <CardHeader>
                  <span className="text-xs font-bold tracking-[0.2em] text-red-700">
                    {number}
                  </span>
                  <CardTitle>{title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-6 text-slate-600">{body}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </Container>
      </section>

      <section className="border-t border-slate-200 bg-white py-16 sm:py-20">
        <Container className="grid gap-12 lg:grid-cols-[0.8fr_1.2fr]">
          <SectionHeading
            eyebrow="FAQ"
            title="Questions members ask."
            description="If an answer depends on legal or financial readiness, the site says so plainly."
          />
          <div className="grid gap-4">
            {faqs.map((faq) => (
              <details
                key={faq.question}
                className="group rounded-[var(--radius-card)] border border-slate-200 bg-white p-5"
              >
                <summary className="cursor-pointer list-none text-base font-semibold text-navy-900 marker:hidden">
                  {faq.question}
                </summary>
                <p className="mt-3 text-sm leading-6 text-slate-600">
                  {faq.answer}
                </p>
              </details>
            ))}
          </div>
        </Container>
      </section>
    </>
  );
}
