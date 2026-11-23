import type Stripe from "stripe";

export function paymentsMode(): "test" | "live" {
  return process.env.PAYMENTS_MODE === "live" ? "live" : "test";
}

export function stripeLivemodeMatches(livemode: boolean): boolean {
  return paymentsMode() === "live" ? livemode : !livemode;
}

export function shouldReprocessPaymentEvent(status: string): boolean {
  return status === "failed";
}

export function isActiveSubscriptionStatus(status: string): boolean {
  return ["active", "trialing", "past_due", "unpaid"].includes(status);
}

export type PaymentEventSummary = {
  amountCents: number | null;
  currency: string | null;
  customerId: string | null;
  subscriptionId: string | null;
  summary: Record<string, unknown>;
};

function objectId(
  value: string | { id: string } | null | undefined,
): string | null {
  if (!value) return null;
  return typeof value === "string" ? value : value.id;
}

function invoiceSubscriptionId(invoice: Stripe.Invoice): string | null {
  const parentSubscription = invoice.parent?.subscription_details?.subscription;
  if (parentSubscription) return objectId(parentSubscription);
  const legacy = (invoice as unknown as { subscription?: string | { id: string } })
    .subscription;
  return objectId(legacy);
}

export function summarizePaymentEvent(
  event: Stripe.Event,
): PaymentEventSummary {
  const base = {
    type: event.type,
    livemode: event.livemode,
    eventId: event.id,
    created: event.created,
  };

  if (event.type.startsWith("invoice.")) {
    const invoice = event.data.object as Stripe.Invoice;
    return {
      amountCents: invoice.amount_paid || invoice.amount_due || null,
      currency: invoice.currency ?? null,
      customerId: objectId(invoice.customer),
      subscriptionId: invoiceSubscriptionId(invoice),
      summary: {
        ...base,
        invoiceId: invoice.id,
        status: invoice.status,
      },
    };
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    return {
      amountCents: session.amount_total ?? null,
      currency: session.currency ?? null,
      customerId: objectId(session.customer),
      subscriptionId: objectId(session.subscription),
      summary: {
        ...base,
        checkoutSessionId: session.id,
        mode: session.mode,
      },
    };
  }

  if (event.type.startsWith("customer.subscription.")) {
    const subscription = event.data.object as Stripe.Subscription;
    return {
      amountCents: null,
      currency: subscription.currency ?? null,
      customerId: objectId(subscription.customer),
      subscriptionId: subscription.id,
      summary: {
        ...base,
        subscriptionStatus: subscription.status,
        cancelAtPeriodEnd: subscription.cancel_at_period_end,
      },
    };
  }

  return {
    amountCents: null,
    currency: null,
    customerId: null,
    subscriptionId: null,
    summary: base,
  };
}
