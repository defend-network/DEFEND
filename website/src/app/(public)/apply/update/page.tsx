import type { Metadata } from "next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { ApplicationUpdateForm } from "./update-form";

export const metadata: Metadata = {
  title: "Update Application",
  robots: { index: false, follow: false },
};

export default function ApplicationUpdatePage() {
  return (
    <section className="py-16 sm:py-20">
      <Container>
        <div className="mx-auto max-w-3xl">
          <Eyebrow>Application update</Eyebrow>
          <h1 className="mt-4 text-3xl font-semibold sm:text-4xl">
            Provide the requested information.
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            This secure link is single-use and expires. Submitting updates returns
            your application to administrative review.
          </p>
          <Card className="mt-8">
            <CardHeader>
              <CardTitle>Application update</CardTitle>
            </CardHeader>
            <CardContent>
              <ApplicationUpdateForm />
            </CardContent>
          </Card>
        </div>
      </Container>
    </section>
  );
}
