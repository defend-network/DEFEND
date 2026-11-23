import { NextResponse } from "next/server";
import { eq } from "drizzle-orm";

import { getActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import {
  appBaseUrl,
  canStartCheckout,
  getStripe,
} from "@/lib/payments/stripe";
import { memberships, membershipSubscriptions } from "@/db/schema";

export const dynamic = "force-dynamic";

export async function POST() {
  const actor = await getActor();
  if (!actor) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const configuration = canStartCheckout();
  if (!configuration.ok) {
    return NextResponse.json({ error: configuration.reason }, { status: 503 });
  }

  const db = await getDb();
  const rows = await db
    .select({ stripeCustomerId: membershipSubscriptions.stripeCustomerId })
    .from(membershipSubscriptions)
    .innerJoin(memberships, eq(membershipSubscriptions.membershipId, memberships.id))
    .where(eq(memberships.userId, actor.userId))
    .limit(1);
  const customerId = rows[0]?.stripeCustomerId;
  if (!customerId) {
    return NextResponse.json(
      { error: "No Stripe customer is linked to this membership." },
      { status: 404 },
    );
  }

  const session = await getStripe().billingPortal.sessions.create({
    customer: customerId,
    return_url: `${appBaseUrl()}/members/billing`,
  });
  return NextResponse.json({ url: session.url });
}
