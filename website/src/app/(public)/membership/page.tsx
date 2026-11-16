import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { siteConfig } from "@/lib/config/site";

export const metadata: Metadata = {
  title: "Membership",
  description:
    "DEFEND membership information: $7 per month, one standard tier, application review, and member portal access.",
};

const faqs = [
  {
    question: "Is membership open now?",
    answer:
      "Yes. Applications are being accepted for the Pasco County founding chapter. Every application is reviewed manually.",
  },
  {
    question: "What does membership cost?",
    answer:
      "The proposed standard dues are $7 per month. There is one standard membership tier. Online billing is not active yet.",
  },
  {
    question: "Can I join before paying?",
    answer:
      "Approved applicants can activate an account and access the member portal before live billing is enabled. Membership standing and payment status are tracked separately.",
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

export default function MembershipPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Membership</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              One standard membership. $7 per month.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              DEFEND membership is intended for people who support the
              organization&apos;s lawful mission and want to participate in a
              local chapter. Applications are reviewed by a person.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-12 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <SectionHeading
              eyebrow="Standard membership"
              title="What the standard membership includes."
              description="The following is being developed. Items that are not yet operating are labeled accordingly."
            />
            <ul className="mt-8 grid gap-4 text-sm leading-6 text-slate-700">
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Participation in the Pasco County founding chapter as it develops.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Access to the member portal, profile, and chapter information.
              </li>
              <li className="flex gap-3">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-red-600" />
                Eligibility for programs and volunteer opportunities as they open.
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
              No premium tiers, exclusive patron listings, or invented benefits
              are being offered. If DEFEND adds a benefit later, it will be
              published with its actual availability.
            </Alert>
          </div>

          <aside className="space-y-4">
            <Card className="border-navy-800/10 bg-navy-900 text-white">
              <CardHeader>
                <Eyebrow className="text-red-500">Standard dues</Eyebrow>
                <p className="text-4xl font-semibold text-white">
                  $7<span className="text-base font-normal text-slate-300"> / month</span>
                </p>
                <p className="text-sm leading-6 text-slate-300">
                  One standard tier. Live billing is not active.
                </p>
              </CardHeader>
              <CardContent>
                <Button asChild className="w-full">
                  <Link href="/apply">Apply for Membership</Link>
                </Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Membership vs. payment</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  Membership standing is recorded separately from payment
                  status. Approved founding members may access the portal before
                  live billing is activated. No real charge is collected until
                  legal, financial, processor, and owner readiness are confirmed.
                </p>
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

      <section className="border-y border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <SectionHeading
            eyebrow="How it works"
            title="Application, review, activation, dues."
            description="DEFEND does not create unrestricted instant accounts. Membership begins with an application and a manual review."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-4">
            {[
              ["01", "Apply", "Submit the application form with your details, interests, and chapter preference."],
              ["02", "Review", "An administrator reviews the application and records a decision."],
              ["03", "Activate", "Approved applicants receive an invitation to create an account."],
              ["04", "Dues", "When live billing is approved, members authorize the $7 monthly subscription."],
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

      <section className="py-16 sm:py-20">
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
