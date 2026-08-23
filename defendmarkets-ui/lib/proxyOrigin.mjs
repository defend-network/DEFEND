// SERVER-ONLY backend target resolver. The browser never sees the raw API port
// and never selects the upstream. The target is constrained to loopback only —
// an arbitrary/external host is rejected so this can never become a generic
// SSRF proxy. The canonical Markets API port derives from the product-owned
// MARKETS_API_PORT (default 8500).
/**
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export function resolveInternalApiOrigin(env = process.env) {
  const configured = env.MARKETS_INTERNAL_API_ORIGIN;
  if (!configured) {
    const port = env.MARKETS_API_PORT ?? "8500";
    return `http://127.0.0.1:${port}`;
  }
  let parsed;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error("MARKETS_INTERNAL_API_ORIGIN must be a valid http URL");
  }
  if (parsed.protocol !== "http:") {
    throw new Error("MARKETS_INTERNAL_API_ORIGIN must use http (loopback only)");
  }
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host !== "127.0.0.1" && host !== "localhost" && host !== "::1") {
    throw new Error(
      "MARKETS_INTERNAL_API_ORIGIN must be a loopback host (127.0.0.1/localhost/::1); external upstreams are not permitted",
    );
  }
  return parsed.origin;
}
