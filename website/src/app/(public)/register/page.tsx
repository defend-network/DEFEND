import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { FreeRegistrationForm } from "./register-form";

export const metadata: Metadata = {
  title: "Create a Free Account",
  description:
    "Create a free DEFEND account for announcements and eligible public events.",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default function RegisterPage() {
  return (
    <section className="py-16 sm:py-20">
      <Container className="grid gap-10 lg:grid-cols-[1fr_0.9fr]">
        <div>
          <Eyebrow>Free account</Eyebrow>
          <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
            Join the network at the Free tier.
          </h1>
          <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
            Free accounts can view announcements and register for eligible public
            events. Workshops, gym access, volunteering, and the business
            directory require Standard membership or higher.
          </p>
          <Alert tone="info" className="mt-8">
            Free registration is adult-only at launch. Youth programming, public
            youth registration, and youth data collection remain disabled.
          </Alert>
          <div className="mt-8 grid gap-3 text-sm leading-6 text-slate-600">
            <p>
              Already have an account?{" "}
              <Link href="/login" className="font-semibold text-red-700 underline-offset-4 hover:underline">
                Sign in
              </Link>
              .
            </p>
            <p>
              Want a paid tier?{" "}
              <Link href="/membership" className="font-semibold text-red-700 underline-offset-4 hover:underline">
                Compare membership tiers
              </Link>
              .
            </p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Create a free account</CardTitle>
            <p className="text-sm leading-6 text-slate-600">
              Email verification is required. No payment method is collected.
            </p>
          </CardHeader>
          <CardContent>
            <FreeRegistrationForm />
          </CardContent>
        </Card>
      </Container>
    </section>
  );
}
