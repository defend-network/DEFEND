import { afterEach, describe, expect, it } from "vitest";
import type Stripe from "stripe";

import {
  isActiveSubscriptionStatus,
  paymentsMode,
  shouldReprocessPaymentEvent,
  stripeLivemodeMatches,
  summarizePaymentEvent,
} from "./events";

const originalMode = process.env.PAYMENTS_MODE;

afterEach(() => {
  if (originalMode === undefined) delete process.env.PAYMENTS_MODE;
  else process.env.PAYMENTS_MODE = originalMode;
});

function event(type: string, object: unknown, livemode = false): Stripe.Event {
  return {
    id: "evt_test",
    type,
    livemode,
    created: 1_700_000_000,
    data: { object },
  } as unknown as Stripe.Event;
}

describe("payment event integrity helpers", () => {
  it("defaults to test mode", () => {
    delete process.env.PAYMENTS_MODE;
    expect(paymentsMode()).toBe("test");
    expect(stripeLivemodeMatches(false)).toBe(true);
    expect(stripeLivemodeMatches(true)).toBe(false);
  });

  it("matches live events only in live mode", () => {
    process.env.PAYMENTS_MODE = "live";
    expect(stripeLivemodeMatches(true)).toBe(true);
    expect(stripeLivemodeMatches(false)).toBe(false);
  });

  it("reprocesses failed events but not processed duplicates", () => {
    expect(shouldReprocessPaymentEvent("failed")).toBe(true);
    expect(shouldReprocessPaymentEvent("processed")).toBe(false);
    expect(shouldReprocessPaymentEvent("received")).toBe(false);
  });

  it("identifies active subscription states", () => {
    expect(isActiveSubscriptionStatus("active")).toBe(true);
    expect(isActiveSubscriptionStatus("trialing")).toBe(true);
    expect(isActiveSubscriptionStatus("past_due")).toBe(true);
    expect(isActiveSubscriptionStatus("unpaid")).toBe(true);
    expect(isActiveSubscriptionStatus("canceled")).toBe(false);
    expect(isActiveSubscriptionStatus("pending_checkout")).toBe(false);
  });

  it("summarizes invoice amounts and subscription identity", () => {
    const summary = summarizePaymentEvent(
      event("invoice.paid", {
        id: "in_test",
        amount_paid: 10800,
        amount_due: 10800,
        currency: "usd",
        status: "paid",
        customer: "cus_test",
        parent: {
          subscription_details: { subscription: "sub_test" },
        },
      }),
    );
    expect(summary.amountCents).toBe(10800);
    expect(summary.currency).toBe("usd");
    expect(summary.customerId).toBe("cus_test");
    expect(summary.subscriptionId).toBe("sub_test");
  });

  it("summarizes checkout totals", () => {
    const summary = summarizePaymentEvent(
      event("checkout.session.completed", {
        id: "cs_test",
        amount_total: 1000,
        currency: "usd",
        customer: "cus_test",
        subscription: "sub_test",
        mode: "subscription",
      }),
    );
    expect(summary.amountCents).toBe(1000);
    expect(summary.subscriptionId).toBe("sub_test");
  });

  it("summarizes subscription events without inventing an amount", () => {
    const summary = summarizePaymentEvent(
      event("customer.subscription.updated", {
        id: "sub_test",
        customer: "cus_test",
        currency: "usd",
        status: "past_due",
        cancel_at_period_end: false,
      }),
    );
    expect(summary.amountCents).toBeNull();
    expect(summary.subscriptionId).toBe("sub_test");
  });
});
