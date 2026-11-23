import type { Metadata } from "next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { NewsletterForm } from "./newsletter-form";

export const metadata: Metadata = {
  title: "Newsletter",
  description: "Subscribe to occasional DEFEND organizational updates with consent.",
};

export default function NewsletterPage() {
  return (
    <section className="py-16 sm:py-20">
      <Container className="grid gap-10 lg:grid-cols-[1fr_1fr]">
        <div>
          <Eyebrow>Newsletter</Eyebrow>
          <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
            Organizational updates, with consent.
          </h1>
          <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
            DEFEND will send occasional organizational updates when an approved
            communications process is ready. This is not a membership application
            and does not create a member account.
          </p>
          <p className="mt-4 text-sm leading-6 text-slate-500">
            No bulk email has been sent from this staging environment. Consent is
            recorded for future approved communications.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Subscribe</CardTitle>
          </CardHeader>
          <CardContent>
            <NewsletterForm />
          </CardContent>
        </Card>
      </Container>
    </section>
  );
}
