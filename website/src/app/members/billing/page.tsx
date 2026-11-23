import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { eq } from "drizzle-orm";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { getMemberStanding } from "@/lib/membership/access";
import { getMemberAccount } from "@/lib/membership/profile";
import { canStartCheckout } from "@/lib/payments/stripe";
import { membershipSubscriptions } from "@/db/schema";
import { BillingActions } from "./billing-actions";

export const metadata: Metadata = {
  title: "Billing",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function BillingPage() {
  const actor = await getActor();
  if (!actor) redirect("/login?next=/members/billing");
  const account = await getMemberAccount(actor.userId);
  const standing = await getMemberStanding(actor.userId);
  const db = await getDb();
  const subscriptionRows = account.membership
    ? await db
        .select()
        .from(membershipSubscriptions)
        .where(eq(membershipSubscriptions.membershipId, account.membership.id))
        .limit(1)
    : [];
  const subscription = subscriptionRows[0];
  const configuration = canStartCheckout();

  if (standing?.status === "free_access") {
    return (
      <div className="grid gap-6">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Billing
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Free account</h1>
        </div>
        <Card>
          <CardContent className="grid gap-4 p-6">
            <p className="text-sm leading-6 text-slate-600">
              Your account is on the Free tier. No payment method is stored and
              no subscription is active. Paid membership requires an approved
              application and explicit payment authorization.
            </p>
            <Button asChild>
              <Link href="/membership">Compare membership tiers</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Billing
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Dues and payments</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Paid membership follows the approved tier catalog. Live payments are
          disabled. This page uses Stripe test mode when configured.
        </p>
      </div>

      <Alert tone="warning">
        No real card is charged from this development environment. A Stripe test
        subscription is linked only when test-mode credentials are configured.
        Membership standing remains separate from payment status.
      </Alert>

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Membership</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm text-slate-600">
            <p><strong className="text-navy-900">Member number:</strong> {account.membership?.memberNumber ?? "—"}</p>
            <p><strong className="text-navy-900">Standing:</strong> {account.membership?.status.replaceAll("_", " ") ?? "—"}</p>
            <p><strong className="text-navy-900">Dues status:</strong> {account.membership?.duesStatus.replaceAll("_", " ") ?? "—"}</p>
            <p><strong className="text-navy-900">Tier:</strong> {standing?.tierName ?? "Not assigned"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Stripe test subscription</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm text-slate-600">
            {subscription ? (
              <>
                <p><strong className="text-navy-900">Status:</strong> {subscription.status}</p>
                <p><strong className="text-navy-900">Renews/ends:</strong> {subscription.currentPeriodEnd ? subscription.currentPeriodEnd.toLocaleDateString() : "—"}</p>
                {subscription.cancelAtPeriodEnd ? <Badge variant="amber">Cancels at period end</Badge> : null}
              </>
            ) : (
              <p>No subscription is linked yet.</p>
            )}
            <BillingActions
              configured={configuration.ok}
              hasCustomer={Boolean(subscription?.stripeCustomerId)}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
