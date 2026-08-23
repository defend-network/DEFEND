/** @type {import("next").NextConfig} */
import { resolveInternalApiOrigin } from "./lib/proxyOrigin.mjs";

const nextConfig = {
  output: "standalone",

  async rewrites() {
    const api = resolveInternalApiOrigin();

    return [
      { source: "/api/markets/:path*", destination: `${api}/api/markets/:path*` },
      { source: "/v1/:path*", destination: `${api}/v1/:path*` },
      { source: "/markets-health", destination: `${api}/health` },
    ];
  },
};
export default nextConfig;
