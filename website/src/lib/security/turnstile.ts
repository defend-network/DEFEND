import { isLocalEnvironment } from "@/lib/config/env";

export async function verifyTurnstile(
  token: string,
  remoteIp?: string | null,
): Promise<{ ok: boolean; configured: boolean; error?: string }> {
  const secret = process.env.TURNSTILE_SECRET_KEY?.trim();
  if (!secret) {
    if (!isLocalEnvironment()) {
      return {
        ok: false,
        configured: false,
        error: "Spam protection is not configured.",
      };
    }
    return { ok: true, configured: false };
  }

  if (!token) {
    return { ok: false, configured: true, error: "Complete the spam check." };
  }

  try {
    const body = new URLSearchParams({ secret, response: token });
    if (remoteIp) body.set("remoteip", remoteIp);
    const response = await fetch(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify",
      {
        method: "POST",
        body,
      },
    );
    const data = (await response.json()) as { success?: boolean };
    return data.success
      ? { ok: true, configured: true }
      : { ok: false, configured: true, error: "Spam check failed." };
  } catch {
    return {
      ok: false,
      configured: true,
      error: "Spam check is temporarily unavailable.",
    };
  }
}
