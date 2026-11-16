import Stripe from "stripe";

let stripeClient: Stripe | null = null;

export function stripeConfigured(): boolean {
  return Boolean(
    process.env.STRIPE_SECRET_KEY?.trim() &&
      process.env.STRIPE_PRICE_ID?.trim(),
  );
}

export function paymentsMode(): "test" | "live" {
  return process.env.PAYMENTS_MODE === "live" ? "live" : "test";
}

export function livePaymentsApproved(): boolean {
  return process.env.PAYMENTS_LIVE_APPROVED === "true";
}

export function canStartCheckout(): { ok: boolean; reason?: string } {
  if (!stripeConfigured()) {
    return { ok: false, reason: "Stripe test-mode credentials are not configured." };
  }
  if (paymentsMode() === "live" && !livePaymentsApproved()) {
    return { ok: false, reason: "Live payments have not been approved." };
  }
  return { ok: true };
}

export function getStripe(): Stripe {
  const key = process.env.STRIPE_SECRET_KEY?.trim();
  if (!key) throw new Error("STRIPE_SECRET_KEY is not configured.");
  if (!stripeClient) {
    stripeClient = new Stripe(key);
  }
  return stripeClient;
}

export function appBaseUrl(): string {
  return (process.env.APP_URL ?? "http://localhost:3000").replace(/\/$/, "");
}
