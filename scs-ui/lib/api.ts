const REQUEST_TIMEOUT_MS = 15000;

let cachedOrigin: string | null = null;

async function resolveOrigin(): Promise<string> {
  if (cachedOrigin) {
    return cachedOrigin;
  }
  try {
    const response = await fetch("/api/runtime-config", {
      cache: "no-store",
    });
    if (response.ok) {
      const payload = (await response.json()) as {
        scsApiOrigin?: string;
      };
      if (payload.scsApiOrigin) {
        cachedOrigin = payload.scsApiOrigin;
        return cachedOrigin;
      }
    }
  } catch {
    // fall through to the loopback default
  }
  cachedOrigin = "http://127.0.0.1:8100";
  return cachedOrigin;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const origin = await resolveOrigin();
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${origin}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
      signal: controller.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw new ApiError("SCS request timed out — is the API running?", 0);
    }
    throw new Error("Could not reach the SCS API");
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    let message = "SCS request failed";
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}