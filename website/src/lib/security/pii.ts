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

async function piiKey(): Promise<CryptoKey> {
  const configured =
    process.env.PII_ENCRYPTION_KEY?.trim() ||
    (process.env.NODE_ENV === "production"
      ? undefined
      : process.env.BETTER_AUTH_SECRET?.trim());
  if (!configured) {
    throw new Error("PII encryption is not configured.");
  }
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(configured),
  );
  return crypto.subtle.importKey("raw", digest, "AES-GCM", false, [
    "encrypt",
    "decrypt",
  ]);
}

export async function encryptPii(plaintext: string): Promise<string> {
  const key = await piiKey();
  const iv = new Uint8Array(12);
  crypto.getRandomValues(iv);
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(plaintext),
  );
  return `v1:${base64Url(iv)}:${base64Url(new Uint8Array(ciphertext))}`;
}

export async function decryptPii(encoded: string): Promise<string> {
  const [version, ivText, ciphertextText] = encoded.split(":");
  if (version !== "v1" || !ivText || !ciphertextText) {
    throw new Error("Unsupported encrypted value.");
  }
  const key = await piiKey();
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64Url(ivText) as BufferSource },
    key,
    fromBase64Url(ciphertextText) as BufferSource,
  );
  return new TextDecoder().decode(plaintext);
}
