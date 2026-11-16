function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64Url(value: string): Uint8Array {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function signingKey(): Promise<CryptoKey> {
  const secret =
    process.env.CARD_TOKEN_SECRET?.trim() ||
    process.env.BETTER_AUTH_SECRET?.trim();
  if (!secret) throw new Error("Card token signing is not configured.");
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(secret),
  );
  return crypto.subtle.importKey(
    "raw",
    digest,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export type CardTokenPayload = {
  membershipId: string;
  userId: string;
  expiresAt: number;
};

export async function createCardToken(
  payload: Omit<CardTokenPayload, "expiresAt"> & { ttlSeconds?: number },
): Promise<{ token: string; expiresAt: Date }> {
  const expiresAt = Date.now() + (payload.ttlSeconds ?? 300) * 1000;
  const body = base64Url(
    new TextEncoder().encode(
      JSON.stringify({
        membershipId: payload.membershipId,
        userId: payload.userId,
        expiresAt,
        nonce: crypto.randomUUID(),
      }),
    ),
  );
  const key = await signingKey();
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(body),
  );
  return {
    token: `v1.${body}.${base64Url(new Uint8Array(signature))}`,
    expiresAt: new Date(expiresAt),
  };
}

export async function verifyCardToken(
  token: string,
): Promise<CardTokenPayload | null> {
  if (!token || token.length > 2048) return null;
  const [version, body, signature] = token.split(".");
  if (version !== "v1" || !body || !signature) return null;

  try {
    const key = await signingKey();
    const valid = await crypto.subtle.verify(
      "HMAC",
      key,
      fromBase64Url(signature) as BufferSource,
      new TextEncoder().encode(body),
    );
    if (!valid) return null;
    const parsed = JSON.parse(
      new TextDecoder().decode(fromBase64Url(body)),
    ) as CardTokenPayload & { nonce?: string };
    if (
      typeof parsed.membershipId !== "string" ||
      typeof parsed.userId !== "string" ||
      typeof parsed.expiresAt !== "number" ||
      parsed.expiresAt <= Date.now()
    ) {
      return null;
    }
    return {
      membershipId: parsed.membershipId,
      userId: parsed.userId,
      expiresAt: parsed.expiresAt,
    };
  } catch {
    return null;
  }
}
