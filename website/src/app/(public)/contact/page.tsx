import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { siteConfig } from "@/lib/config/site";
import { ContactForm } from "./contact-form";

export const metadata: Metadata = {
  title: "Contact",
  description: "Contact DEFEND about membership, partnerships, or the founding chapter.",
};

export default function ContactPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Contact</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Start a conversation.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              Use the form for membership questions, partnership inquiries,
              property or facility leads, or general organizational questions.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr]">
          <Card>
            <CardHeader>
              <CardTitle>Send a message</CardTitle>
              <p className="text-sm leading-6 text-slate-500">
                Messages are stored in the DEFEND administrative system. A
                notification email will be added when the email integration is
                configured.
              </p>
            </CardHeader>
            <CardContent>
              <ContactForm />
            </CardContent>
          </Card>

          <div className="space-y-5">
            <Card>
              <CardHeader>
                <CardTitle>Direct email</CardTitle>
              </CardHeader>
              <CardContent>
                <a
                  href={`mailto:${siteConfig.contactEmail}`}
                  className="text-sm font-semibold text-red-700 underline-offset-4 hover:underline"
                >
                  {siteConfig.contactEmail}
                </a>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Founding chapter</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  Pasco County, Florida. The chapter is in development and is
                  recruiting founding participants.
                </p>
              </CardContent>
            </Card>
            <Alert tone="info">
              Do not send passwords, payment card details, government
              identifiers, or other sensitive personal information through this
              form.
            </Alert>
          </div>
        </Container>
      </section>
    </>
  );
}
