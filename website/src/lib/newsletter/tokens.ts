const DEVELOPMENT_SECRET =
  "defend-development-newsletter-unsubscribe-token-not-for-production";

function secret(): string {
  const configured =
    process.env.NEWSLETTER_UNSUBSCRIBE_SECRET?.trim() ||
    process.env.CARD_TOKEN_SECRET?.trim() ||
    process.env.BETTER_AUTH_SECRET?.trim();
  if (configured) return configured;
  if (process.env.APP_ENV === "production") {
    throw new Error("Newsletter unsubscribe secret is not configured.");
  }
  return DEVELOPMENT_SECRET;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlDecode(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/").padEnd(
    Math.ceil(value.length / 4) * 4,
    "=",
  );
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0)) as Uint8Array<ArrayBuffer>;
}

async function hmacKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function createUnsubscribeToken(subscriberId: string): Promise<string> {
  const payload = base64UrlEncode(new TextEncoder().encode(subscriberId));
  const signature = await crypto.subtle.sign(
    "HMAC",
    await hmacKey(),
    new TextEncoder().encode(payload),
  );
  return `v1.${payload}.${base64UrlEncode(new Uint8Array(signature))}`;
}

export async function verifyUnsubscribeToken(
  token: string,
): Promise<{ valid: false } | { valid: true; subscriberId: string }> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "v1" || !parts[1] || !parts[2]) {
    return { valid: false };
  }
  try {
    const valid = await crypto.subtle.verify(
      "HMAC",
      await hmacKey(),
      base64UrlDecode(parts[2]),
      new TextEncoder().encode(parts[1]),
    );
    if (!valid) return { valid: false };
    const subscriberId = new TextDecoder().decode(base64UrlDecode(parts[1]));
    if (!subscriberId) return { valid: false };
    return { valid: true, subscriberId };
  } catch {
    return { valid: false };
  }
}

export function newsletterUnsubscribeUrl(subscriberId: string): Promise<string> {
  const base = (process.env.APP_URL ?? "http://localhost:3000").replace(/\/$/, "");
  return createUnsubscribeToken(subscriberId).then(
    (token) => `${base}/newsletter/unsubscribe?token=${encodeURIComponent(token)}`,
  );
}
