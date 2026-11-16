import type { Metadata } from "next";

import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { ApplicationForm } from "./application-form";

export const metadata: Metadata = {
  title: "Apply for Membership",
  description:
    "Apply for DEFEND membership. Applications are reviewed manually. Standard dues are $7 per month and online billing is not active.",
};

export default function ApplyPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Membership application</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Apply for the founding chapter.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              DEFEND is accepting applications for the Pasco County founding
              chapter. Every application is reviewed by a person. Submitting this
              form does not create an account or authorize a payment.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-10 lg:grid-cols-[1.15fr_0.85fr]">
          <Card>
            <CardHeader>
              <CardTitle>Application</CardTitle>
              <p className="text-sm leading-6 text-slate-500">
                Fields marked by the browser as required must be completed. Do
                not include payment card details, passwords, government
                identifiers, or other sensitive information.
              </p>
            </CardHeader>
            <CardContent>
              <ApplicationForm />
            </CardContent>
          </Card>

          <aside className="space-y-5">
            <Alert tone="info">
              DEFEND is not yet incorporated and has not received IRS
              recognition. Online dues and donations are not active.
            </Alert>
            <Card>
              <CardHeader>
                <CardTitle>What happens next</CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="grid gap-3 text-sm leading-6 text-slate-600">
                  <li>1. An administrator reviews the application.</li>
                  <li>
                    2. DEFEND may approve, deny, or request more information.
                  </li>
                  <li>
                    3. Approved applicants receive an invitation to activate an
                    account.
                  </li>
                  <li>
                    4. Approved founding members may use the member portal
                    before live billing is enabled.
                  </li>
                </ol>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Privacy</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  Application data is stored in the DEFEND administrative system
                  and is available only to authorized reviewers. Phone numbers
                  are encrypted at rest. Do not send sensitive information
                  through the optional text fields.
                </p>
              </CardContent>
            </Card>
          </aside>
        </Container>
      </section>
    </>
  );
}
