import type { Metadata } from "next";
import { eq } from "drizzle-orm";

import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { getDb } from "@/lib/db/client";
import { newsletterSubscribers } from "@/db/schema";
import { verifyUnsubscribeToken } from "@/lib/newsletter/tokens";
import { UnsubscribeForm } from "./unsubscribe-form";

export const metadata: Metadata = {
  title: "Newsletter unsubscribe",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function maskedEmail(email: string): string {
  const [local, domain] = email.split("@");
  if (!local || !domain) return "this address";
  return `${local.slice(0, 1)}***@${domain}`;
}

export default async function UnsubscribePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const params = await searchParams;
  const token = params.token ?? "";
  const verified = token ? await verifyUnsubscribeToken(token) : { valid: false as const };

  let subscriber:
    | { id: string; email: string; status: string }
    | undefined;
  if (verified.valid) {
    const db = await getDb();
    const rows = await db
      .select({
        id: newsletterSubscribers.id,
        email: newsletterSubscribers.email,
        status: newsletterSubscribers.status,
      })
      .from(newsletterSubscribers)
      .where(eq(newsletterSubscribers.id, verified.subscriberId))
      .limit(1);
    subscriber = rows[0];
  }

  return (
    <section className="py-16 sm:py-20">
      <Container className="max-w-2xl">
        <Eyebrow>Newsletter</Eyebrow>
        <h1 className="mt-5 text-4xl font-semibold leading-tight">
          Unsubscribe from updates.
        </h1>
        <Card className="mt-8">
          <CardHeader>
            <CardTitle>Communication preferences</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            {!verified.valid || !subscriber ? (
              <Alert tone="error" role="alert">
                This unsubscribe link is invalid or incomplete. Contact DEFEND if
                you need help changing your communication preferences.
              </Alert>
            ) : subscriber.status === "unsubscribed" ? (
              <Alert tone="success" role="status">
                {maskedEmail(subscriber.email)} is already unsubscribed from
                DEFEND organizational updates.
              </Alert>
            ) : (
              <>
                <p className="text-sm leading-6 text-slate-600">
                  Confirm that {maskedEmail(subscriber.email)} should stop
                  receiving DEFEND organizational updates. This does not affect
                  membership, account, or transactional messages.
                </p>
                <UnsubscribeForm token={token} />
              </>
            )}
          </CardContent>
        </Card>
      </Container>
    </section>
  );
}
