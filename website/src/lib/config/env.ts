export type RuntimeEnvironment = "development" | "test" | "staging" | "production";

const VALID_ENVIRONMENTS: ReadonlySet<string> = new Set([
  "development",
  "test",
  "staging",
  "production",
]);

export function runtimeEnvironment(): RuntimeEnvironment {
  const raw = (
    process.env.APP_ENV?.trim() ||
    process.env.NODE_ENV?.trim() ||
    "development"
  ).toLowerCase();

  if (!VALID_ENVIRONMENTS.has(raw)) {
    throw new Error(`Unsupported APP_ENV value: ${raw}`);
  }

  return raw as RuntimeEnvironment;
}

export function isLocalEnvironment(): boolean {
  const environment = runtimeEnvironment();
  return environment === "development" || environment === "test";
}

export function isDeployedEnvironment(): boolean {
  return !isLocalEnvironment();
}

export function requireSecret(name: string): string {
  const value = process.env[name]?.trim();
  if (value) return value;
  throw new Error(`${name} is required in ${runtimeEnvironment()}.`);
}

export function resolveSecret(name: string, localFallback: string): string {
  const value = process.env[name]?.trim();
  if (value) return value;
  if (isLocalEnvironment()) return localFallback;
  throw new Error(`${name} is required in ${runtimeEnvironment()}.`);
}

export function optionalSecret(name: string): string | null {
  return process.env[name]?.trim() || null;
}

export function secureCookiesRequired(): boolean {
  return isDeployedEnvironment();
}
