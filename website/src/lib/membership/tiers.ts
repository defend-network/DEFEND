import { and, asc, eq, gte, isNull, lte, or } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { membershipTierPrices, membershipTiers } from "@/db/schema";

export const ANNUAL_DISCOUNT_RATE = 0.9;
export const PATRON_MINIMUM_MONTHLY_CENTS = 5000;

export type BillingInterval = "month" | "year";

export function annualPriceCents(monthlyCents: number): number {
  return Math.round(monthlyCents * 12 * ANNUAL_DISCOUNT_RATE);
}

export function isPatronAmountAllowed(monthlyCents: number): boolean {
  return Number.isFinite(monthlyCents) && monthlyCents >= PATRON_MINIMUM_MONTHLY_CENTS;
}

export async function listActiveTiers() {
  const db = await getDb();
  return db
    .select()
    .from(membershipTiers)
    .where(eq(membershipTiers.active, true))
    .orderBy(asc(membershipTiers.rank));
}

export async function getTierByKey(key: string) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(membershipTiers)
    .where(eq(membershipTiers.key, key))
    .limit(1);
  return rows[0] ?? null;
}

export async function getActivePrice(
  tierId: string,
  interval: BillingInterval,
  at = new Date(),
) {
  const db = await getDb();
  const rows = await db
    .select()
    .from(membershipTierPrices)
    .where(
      and(
        eq(membershipTierPrices.tierId, tierId),
        eq(membershipTierPrices.interval, interval),
        eq(membershipTierPrices.active, true),
        lte(membershipTierPrices.effectiveFrom, at),
        or(
          isNull(membershipTierPrices.effectiveTo),
          gte(membershipTierPrices.effectiveTo, at),
        ),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

export type TierCatalogEntry = {
  key: string;
  name: string;
  description: string;
  rank: number;
  minimumMonthlyCents: number;
  allowsCustomAmount: boolean;
  monthlyCents: number | null;
  annualCents: number | null;
};

export async function listTierCatalog(): Promise<TierCatalogEntry[]> {
  const tiers = await listActiveTiers();
  return Promise.all(
    tiers.map(async (tier) => {
      const [monthly, annual] = await Promise.all([
        getActivePrice(tier.id, "month"),
        getActivePrice(tier.id, "year"),
      ]);
      return {
        key: tier.key,
        name: tier.name,
        description: tier.description,
        rank: tier.rank,
        minimumMonthlyCents: tier.minimumMonthlyCents,
        allowsCustomAmount: tier.allowsCustomAmount,
        monthlyCents: monthly?.amountCents ?? null,
        annualCents: annual?.amountCents ?? null,
      };
    }),
  );
}
