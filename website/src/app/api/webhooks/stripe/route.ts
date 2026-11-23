import { NextResponse } from "next/server";
import { eq } from "drizzle-orm";
import type Stripe from "stripe";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { getStripe } from "@/lib/payments/stripe";
import {
  shouldReprocessPaymentEvent,
  stripeLivemodeMatches,
  summarizePaymentEvent,
} from "@/lib/payments/events";
import {
  memberships,
  membershipStatusHistory,
  membershipSubscriptions,
  paymentEvents,
} from "@/db/schema";

export const dynamic = "force-dynamic";

function timestamp(value: number | null | undefined): Date | null {
  return value ? new Date(value * 1000) : null;
}

function invoiceSubscriptionId(invoice: Stripe.Invoice): string | null {
  const subscription = invoice.parent?.subscription_details?.subscription;
  if (typeof subscription === "string") return subscription;
  return subscription?.id ?? null;
}

async function setMembershipState(input: {
  membershipId: string;
  status: string;
  duesStatus: string;
  reason: string;
}) {
  const db = await getDb();
  const rows = await db
    .select({ status: memberships.status, duesStatus: memberships.duesStatus })
    .from(memberships)
    .where(eq(memberships.id, input.membershipId))
    .limit(1);
  const current = rows[0];
  if (!current) return;
  if (
    current.status === input.status &&
    current.duesStatus === input.duesStatus
  ) {
    return;
  }

  await db
    .update(memberships)
    .set({
      status: input.status,
      duesStatus: input.duesStatus,
      updatedAt: new Date(),
    })
    .where(eq(memberships.id, input.membershipId));

  await db.insert(membershipStatusHistory).values({
    id: `msh_${crypto.randomUUID()}`,
    membershipId: input.membershipId,
    fromStatus: current.status,
    toStatus: input.status,
    reason: input.reason,
    actorId: null,
    createdAt: new Date(),
  });

  await recordAuditEvent({
    actorUserId: null,
    action: "payment.membership.sync",
    targetType: "membership",
    targetId: input.membershipId,
    outcome: "success",
    metadata: {
      fromStatus: current.status,
      toStatus: input.status,
      duesStatus: input.duesStatus,
      reason: input.reason,
    },
  });
}

async function syncSubscription(subscription: Stripe.Subscription) {
  const db = await getDb();
  const customerId =
    typeof subscription.customer === "string"
      ? subscription.customer
      : subscription.customer.id;
  const priceId = subscription.items.data[0]?.price?.id ?? null;
  const periodItem = subscription.items.data[0];

  const bySubscription = await db
    .select()
    .from(membershipSubscriptions)
    .where(eq(membershipSubscriptions.stripeSubscriptionId, subscription.id))
    .limit(1);
  const byCustomer = bySubscription[0]
    ? []
    : await db
        .select()
        .from(membershipSubscriptions)
        .where(eq(membershipSubscriptions.stripeCustomerId, customerId))
        .limit(1);
  const local = bySubscription[0] ?? byCustomer[0];
  if (!local) return;

  await db
    .update(membershipSubscriptions)
    .set({
      stripeCustomerId: customerId,
      stripeSubscriptionId: subscription.id,
      priceId,
      status: subscription.status,
      currentPeriodStart: timestamp(periodItem?.current_period_start),
      currentPeriodEnd: timestamp(periodItem?.current_period_end),
      cancelAtPeriodEnd: subscription.cancel_at_period_end,
      updatedAt: new Date(),
    })
    .where(eq(membershipSubscriptions.id, local.id));

  if (subscription.status === "active" || subscription.status === "trialing") {
    await setMembershipState({
      membershipId: local.membershipId,
      status: "active",
      duesStatus: "paid",
      reason: "Stripe subscription active",
    });
  } else if (
    subscription.status === "past_due" ||
    subscription.status === "unpaid"
  ) {
    await setMembershipState({
      membershipId: local.membershipId,
      status: "grace",
      duesStatus: "failed",
      reason: "Stripe subscription payment failed",
    });
  } else if (subscription.status === "canceled") {
    await setMembershipState({
      membershipId: local.membershipId,
      status: "cancelled",
      duesStatus: "cancelled",
      reason: "Stripe subscription canceled",
    });
  }
}

export async function POST(request: Request) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET?.trim();
  const signature = request.headers.get("stripe-signature");
  if (!secret || !signature) {
    return NextResponse.json(
      { error: "Stripe webhook is not configured." },
      { status: 503 },
    );
  }

  const payload = await request.text();
  let event: Stripe.Event;
  try {
    event = getStripe().webhooks.constructEvent(payload, signature, secret);
  } catch {
    return NextResponse.json({ error: "Invalid signature." }, { status: 400 });
  }

  if (!stripeLivemodeMatches(event.livemode)) {
    return NextResponse.json(
      { error: "Stripe event mode does not match the configured payment mode." },
      { status: 400 },
    );
  }

  const db = await getDb();
  const eventSummary = summarizePaymentEvent(event);
  const summaryValues = {
    stripeCustomerId: eventSummary.customerId,
    stripeSubscriptionId: eventSummary.subscriptionId,
    amountCents: eventSummary.amountCents,
    currency: eventSummary.currency,
    payloadSummaryJson: JSON.stringify(eventSummary.summary),
  };
  const inserted = await db
    .insert(paymentEvents)
    .values({
      id: `pe_${crypto.randomUUID()}`,
      stripeEventId: event.id,
      type: event.type,
      status: "received",
      occurredAt: new Date(event.created * 1000),
      ...summaryValues,
    })
    .onConflictDoNothing({ target: paymentEvents.stripeEventId })
    .returning({ id: paymentEvents.id });

  if (inserted.length === 0) {
    const existingRows = await db
      .select({ status: paymentEvents.status })
      .from(paymentEvents)
      .where(eq(paymentEvents.stripeEventId, event.id))
      .limit(1);
    const existing = existingRows[0];
    if (!existing || !shouldReprocessPaymentEvent(existing.status)) {
      return NextResponse.json({ received: true, duplicate: true });
    }
    await db
      .update(paymentEvents)
      .set({
        status: "received",
        processedAt: null,
        ...summaryValues,
      })
      .where(eq(paymentEvents.stripeEventId, event.id));
  }

  try {
    if (event.type === "checkout.session.completed") {
      const session = event.data.object as Stripe.Checkout.Session;
      if (typeof session.subscription === "string") {
        const subscription = await getStripe().subscriptions.retrieve(
          session.subscription,
        );
        await syncSubscription(subscription);
      }
    } else if (
      event.type === "customer.subscription.created" ||
      event.type === "customer.subscription.updated" ||
      event.type === "customer.subscription.deleted"
    ) {
      await syncSubscription(event.data.object as Stripe.Subscription);
    } else if (event.type === "invoice.paid") {
      const invoice = event.data.object as Stripe.Invoice;
      const subscriptionId = invoiceSubscriptionId(invoice);
      if (subscriptionId) {
        const subscription =
          await getStripe().subscriptions.retrieve(subscriptionId);
        await syncSubscription(subscription);
      }
    } else if (event.type === "invoice.payment_failed") {
      const invoice = event.data.object as Stripe.Invoice;
      const subscriptionId = invoiceSubscriptionId(invoice);
      if (subscriptionId) {
        const subscription =
          await getStripe().subscriptions.retrieve(subscriptionId);
        await syncSubscription(subscription);
      }
    }

    await db
      .update(paymentEvents)
      .set({
        status: "processed",
        processedAt: new Date(),
        ...summaryValues,
      })
      .where(eq(paymentEvents.stripeEventId, event.id));

    return NextResponse.json({ received: true });
  } catch {
    await db
      .update(paymentEvents)
      .set({
        status: "failed",
        processedAt: new Date(),
        ...summaryValues,
      })
      .where(eq(paymentEvents.stripeEventId, event.id));
    return NextResponse.json(
      { error: "Webhook processing failed." },
      { status: 500 },
    );
  }
}
