import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";

export const metadata: Metadata = {
  title: "Volunteer",
  description:
    "Volunteer with DEFEND in Pasco County. Event, community service, mentorship, trades, and administrative opportunities.",
};

export default function VolunteerLandingPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Volunteer</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Serve the founding chapter.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              DEFEND volunteers help with events, community service, mentorship,
              trades education, and administrative work. Published opportunities
              appear in the member portal when they are confirmed.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-10 lg:grid-cols-[1fr_1fr]">
          <div className="grid gap-5">
            <SectionHeading
              eyebrow="Ways to help"
              title="Practical service, not a mailing list."
              description="Volunteer roles have real requirements and may require membership, availability, skills, or screening. Youth-related roles remain disabled until safeguarding requirements are approved."
            />
            <ul className="grid gap-3 text-sm leading-6 text-slate-600">
              <li>Event setup, welcome, and check-in support.</li>
              <li>Community service and local projects.</li>
              <li>Trades, automotive, and entrepreneurship workshops.</li>
              <li>Mentorship and professional guidance.</li>
              <li>Administrative, outreach, and sponsorship support.</li>
            </ul>
          </div>
          <Card>
            <CardHeader><CardTitle>How to participate</CardTitle></CardHeader>
            <CardContent className="grid gap-4 text-sm leading-6 text-slate-600">
              <ol className="grid gap-3">
                <li>1. Apply for membership if you are not yet a member.</li>
                <li>2. Complete your member profile and volunteer interests.</li>
                <li>3. Register for a published volunteer opportunity.</li>
                <li>4. Wait for confirmation if the role requires review.</li>
              </ol>
              <div className="flex flex-wrap gap-3">
                <Button asChild><Link href="/apply">Apply for membership</Link></Button>
                <Button asChild variant="secondary"><Link href="/login">Member sign in</Link></Button>
              </div>
            </CardContent>
          </Card>
        </Container>
      </section>

      <section className="border-t border-slate-200 bg-white py-14">
        <Container>
          <Alert tone="warning">
            No volunteer opportunity is confirmed until it is published with a
            date, location, and responsible coordinator. DEFEND does not
            fabricate participation or service hours.
          </Alert>
        </Container>
      </section>
    </>
  );
}
