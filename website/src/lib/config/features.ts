function flag(name: string, fallback = false): boolean {
  const value = process.env[name];
  if (value === undefined) return fallback;
  return value === "true" || value === "1";
}

export const featureFlags = {
  applicationsOpen: flag("APPLICATIONS_OPEN", true),
  paymentsLiveApproved: flag("PAYMENTS_LIVE_APPROVED", false),
  donationsEnabled: flag("DONATIONS_ENABLED", false),
  maintenanceMode: flag("MAINTENANCE_MODE", false),
};

export const paymentsMode = process.env.PAYMENTS_MODE === "live" ? "live" : "test";

export function canAcceptLivePayments(): boolean {
  return featureFlags.paymentsLiveApproved && paymentsMode === "live";
}
