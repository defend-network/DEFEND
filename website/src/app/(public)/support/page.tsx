import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { siteConfig } from "@/lib/config/site";

export const metadata: Metadata = {
  title: "Support DEFEND",
  description:
    "Sponsorship, partnership, property, and volunteer inquiries for DEFEND. Online donations are not active.",
};

export default function SupportPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Support DEFEND</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Build the founding chapter with us.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              DEFEND is seeking practical partners, property leads, sponsors, and
              volunteers for the Pasco County founding chapter. Online donations
              are not active.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-5 md:grid-cols-3">
          <Card>
            <CardHeader><CardTitle>Sponsorship &amp; partnership</CardTitle></CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-slate-600">
                Businesses, trades, and community organizations can inquire about
                program sponsorship, in-kind support, or partnership. Terms are
                reviewed individually; no sponsorship is implied until confirmed.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Property &amp; facility</CardTitle></CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-slate-600">
                Property owners and agents can submit lease, donation, or purchase
                leads for a future chapter facility. Property discussions remain
                confidential and internal.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Volunteer</CardTitle></CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-slate-600">
                Volunteers can help with events, community service, mentorship,
                trades education, and administrative work. Some roles require
                membership or screening.
              </p>
              <div className="mt-4">
                <Button asChild variant="secondary" size="sm">
                  <Link href="/volunteer">Volunteer information</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </Container>
      </section>

      <section className="border-y border-slate-200 bg-white py-16 sm:py-20">
        <Container className="grid gap-10 lg:grid-cols-2">
          <SectionHeading
            eyebrow="How to start"
            title="Contact DEFEND directly."
            description="Use the contact form or email the organization. Do not send payment card details, passwords, or sensitive financial information by email."
          />
          <div className="grid gap-4">
            <Alert tone="warning">
              DEFEND is not yet incorporated and has not received IRS recognition.
              No charitable donation is being solicited, and no contribution is
              represented as tax-deductible.
            </Alert>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link href="/contact">Contact DEFEND</Link>
              </Button>
              <Button asChild variant="secondary">
                <a href={`mailto:${siteConfig.contactEmail}`}>{siteConfig.contactEmail}</a>
              </Button>
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
