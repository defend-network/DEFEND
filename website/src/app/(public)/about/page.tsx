import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { siteConfig } from "@/lib/config/site";

export const metadata: Metadata = {
  title: "About",
  description:
    "Learn what DEFEND is, what it is building, and its current organizational status.",
};

const commitments = [
  {
    title: "Lawful and transparent",
    body: "DEFEND intends to operate lawfully and to apply written membership criteria consistently. Membership decisions are made by people, not automated systems.",
  },
  {
    title: "Nonpartisan",
    body: "DEFEND is not a political party or campaign organization. The organization is focused on cultural, fraternal, educational, economic, and community activities.",
  },
  {
    title: "Faith is not a membership test",
    body: "Christian faith is part of the cultural inheritance that informs DEFEND's values. It is not a membership requirement.",
  },
  {
    title: "Honest about status",
    body: "Planned programs and future chapters are labeled as such. DEFEND does not present proposed facilities, programs, or recognition as completed facts.",
  },
];

export default function AboutPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>About DEFEND</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Descendants of Europeans Fraternal Economic Network for Development.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              DEFEND is being organized as a fraternal, cultural, and economic
              network for Americans interested in European heritage. The first
              chapter is in development in Pasco County, Florida.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-12 lg:grid-cols-[1fr_1fr] lg:items-start">
          <div>
            <SectionHeading
              eyebrow="Mission"
              title="Bring people together around heritage, fellowship, and practical opportunity."
              description="DEFEND is intended to support cultural preservation, fraternal fellowship, economic development, entrepreneurship, trades education, mentoring, physical fitness, community improvement, volunteer service, and local chapter development."
            />
          </div>
          <div className="grid gap-4">
            {commitments.map((item) => (
              <Card key={item.title}>
                <CardHeader>
                  <CardTitle>{item.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-6 text-slate-600">{item.body}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </Container>
      </section>

      <section id="status" className="border-y border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <SectionHeading
            eyebrow="Current status"
            title="What is true today."
            description="This page is intentionally specific so members and visitors are not asked to rely on assumptions."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Legal formation</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  DEFEND is not yet legally incorporated. Initial legal planning
                  prioritizes a qualifying 501(c)(3) charitable structure. A
                  separate 501(c)(7) social organization may be evaluated later.
                  No IRS recognition has been received.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Chapters</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  Pasco County is the founding chapter and is in development.
                  Orlando, Pensacola, Tallahassee, and other Florida areas are
                  planned only; they are not operating and have no assigned
                  members.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Dues and donations</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  Membership is offered through the approved Free, Standard,
                  Supporter, and Patron tiers. Current pricing is listed on the
                  membership page. Online dues are not active. DEFEND is not
                  currently soliciting charitable donations or claiming that
                  contributions are tax-deductible.
                </p>
              </CardContent>
            </Card>
          </div>
          <Alert tone="warning" className="mt-6">
            {siteConfig.status.legal} {siteConfig.status.billing}
          </Alert>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-10 lg:grid-cols-[1fr_1fr]">
          <div>
            <SectionHeading
              eyebrow="Governance"
              title="Leadership will be published when it is confirmed."
              description="DEFEND is not inventing officers, biographies, or endorsements. Founding leadership, bylaws, and chapter governance are being developed."
            />
          </div>
          <div>
            <SectionHeading
              eyebrow="What we are not"
              title="No borrowed credibility."
              description="DEFEND does not claim existing facilities, established chapters, public recognition, partnerships, or completed programs that do not exist. We will publish those things only when they are real."
            />
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild>
                <Link href="/membership">Membership information</Link>
              </Button>
              <Button asChild variant="secondary">
                <Link href="/contact">Contact DEFEND</Link>
              </Button>
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
