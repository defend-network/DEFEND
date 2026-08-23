/** @type {import("next").NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      // DEFENDMarkets owner/quant API (loopback-only, same-origin proxy).
      // Placed before the generic /api/:path* rewrite so Markets routes win.
      { source: "/api/markets/:path*", destination: "http://127.0.0.1:8300/api/markets/:path*" },
      // DEFENDMarkets data endpoints (/v1/*) — same-origin proxy to 8300.
      { source: "/v1/:path*", destination: "http://127.0.0.1:8300/v1/:path*" },
      // DEFENDMarkets health probe (distinct from the DEFEND AI /health).
      { source: "/markets-health", destination: "http://127.0.0.1:8300/health" },
      // DEFEND AI backend (unchanged).
      { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
      { source: "/health", destination: "http://127.0.0.1:8000/health" },
    ];
  },
};
export default nextConfig;
