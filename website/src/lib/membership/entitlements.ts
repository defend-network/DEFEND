export const ENTITLEMENT_KEYS = [
  "announcements",
  "public_events",
  "workshops",
  "gym",
  "volunteering",
  "directory",
  "supporter_benefits",
  "patron_benefits",
] as const;

export type EntitlementKey = (typeof ENTITLEMENT_KEYS)[number];

const STANDARD_ENTITLEMENTS: ReadonlySet<EntitlementKey> = new Set([
  "announcements",
  "public_events",
  "workshops",
  "gym",
  "volunteering",
  "directory",
]);

export function tierAllowsEntitlement(
  tierKey: string | null,
  entitlement: EntitlementKey,
): boolean {
  if (!tierKey) return false;
  if (tierKey === "free") {
    return entitlement === "announcements" || entitlement === "public_events";
  }
  if (tierKey === "standard") {
    return STANDARD_ENTITLEMENTS.has(entitlement);
  }
  if (tierKey === "supporter") {
    return (
      STANDARD_ENTITLEMENTS.has(entitlement) ||
      entitlement === "supporter_benefits"
    );
  }
  if (tierKey === "patron") {
    return (
      STANDARD_ENTITLEMENTS.has(entitlement) ||
      entitlement === "supporter_benefits" ||
      entitlement === "patron_benefits"
    );
  }
  return false;
}

export type EntitlementOverride = {
  entitlementKey: string;
  enabled: boolean;
  expiresAt?: Date | null;
};

export function memberHasEntitlement(input: {
  tierKey: string | null;
  entitlement: EntitlementKey;
  overrides?: EntitlementOverride[];
  now?: Date;
}): boolean {
  const now = input.now ?? new Date();
  const override = input.overrides?.find(
    (candidate) =>
      candidate.entitlementKey === input.entitlement &&
      (!candidate.expiresAt || candidate.expiresAt.getTime() > now.getTime()),
  );
  if (override) return override.enabled;
  return tierAllowsEntitlement(input.tierKey, input.entitlement);
}
