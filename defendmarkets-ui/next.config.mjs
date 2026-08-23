/** @type {import("next").NextConfig} */
const nextConfig = {
  output: "standalone",

  async rewrites() {
    // SERVER-ONLY backend target: the browser never sees the raw API port and
    // never selects the upstream. Constrained to the loopback Markets backend.
    const api =
      process.env.MARKETS_INTERNAL_API_ORIGIN ?? "http://127.0.0.1:8500";

    return [
      { source: "/api/markets/:path*", destination: `${api}/api/markets/:path*` },
      { source: "/v1/:path*", destination: `${api}/v1/:path*` },
      { source: "/markets-health", destination: `${api}/health` },
    ];
  },
};
export default nextConfig;
