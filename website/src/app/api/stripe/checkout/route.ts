import { NextResponse } from "next/server";
import { eq } from "drizzle-orm";

import { getActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import {
  appBaseUrl,
  canStartCheckout,
  getStripe,
} from "@/lib/payments/stripe";
import { isActiveSubscriptionStatus } from "@/lib/payments/events";
import { memberships, membershipSubscriptions } from "@/db/schema";

export const dynamic = "force-dynamic";

const eligibleStatuses = new Set([
  "founding_access",
  "pending_payment",
  "active",
  "grace",
]);

export async function POST() {
  const actor = await getActor();
  if (!actor) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const configuration = canStartCheckout();
  if (!configuration.ok) {
    return NextResponse.json(
      { error: configuration.reason },
      { status: 503 },
    );
  }

  const db = await getDb();
  const membershipRows = await db
    .select()
    .from(memberships)
    .where(eq(memberships.userId, actor.userId))
    .limit(1);
  const membership = membershipRows[0];
  if (!membership) {
    return NextResponse.json(
      { error: "No membership record is available." },
      { status: 404 },
    );
  }
  if (!eligibleStatuses.has(membership.status)) {
    return NextResponse.json(
      { error: "Membership is not eligible for a subscription." },
      { status: 403 },
    );
  }

  const stripe = getStripe();
  const subscriptionRows = await db
    .select()
    .from(membershipSubscriptions)
    .where(eq(membershipSubscriptions.membershipId, membership.id));
  const activeSubscription = subscriptionRows.find((row) =>
    isActiveSubscriptionStatus(row.status),
  );
  if (activeSubscription) {
    return NextResponse.json(
      {
        error:
          "An existing subscription is already active. Use the billing portal to manage it.",
        portal: true,
      },
      { status: 409 },
    );
  }
  let subscription = subscriptionRows[0];

  let customerId = subscription?.stripeCustomerId ?? null;
  if (!customerId) {
    const customer = await stripe.customers.create({
      email: actor.email,
      name: actor.displayName,
      metadata: {
        membership_id: membership.id,
        user_id: actor.userId,
      },
    });
    customerId = customer.id;
    if (subscription) {
      await db
        .update(membershipSubscriptions)
        .set({ stripeCustomerId: customerId, updatedAt: new Date() })
        .where(eq(membershipSubscriptions.id, subscription.id));
    } else {
      const id = `sub_${crypto.randomUUID()}`;
      await db.insert(membershipSubscriptions).values({
        id,
        membershipId: membership.id,
        stripeCustomerId: customerId,
        status: "pending_checkout",
        createdAt: new Date(),
        updatedAt: new Date(),
      });
      subscription = {
        id,
        membershipId: membership.id,
        stripeCustomerId: customerId,
        stripeSubscriptionId: null,
        priceId: null,
        tierId: null,
        billingInterval: null,
        status: "pending_checkout",
        currentPeriodStart: null,
        currentPeriodEnd: null,
        cancelAtPeriodEnd: false,
        createdAt: new Date(),
        updatedAt: new Date(),
      };
    }
  }

  const session = await stripe.checkout.sessions.create({
    mode: "subscription",
    customer: customerId,
    line_items: [
      {
        price: process.env.STRIPE_PRICE_ID!,
        quantity: 1,
      },
    ],
    success_url: `${appBaseUrl()}/members/billing?checkout=success`,
    cancel_url: `${appBaseUrl()}/members/billing?checkout=cancelled`,
    client_reference_id: membership.id,
    metadata: {
      membership_id: membership.id,
      user_id: actor.userId,
    },
  });

  return NextResponse.json({ url: session.url });
}
