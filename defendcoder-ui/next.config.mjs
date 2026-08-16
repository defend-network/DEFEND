/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

  async rewrites() {
    const api =
      process.env.DEFENDCODER_INTERNAL_API_URL ??
      "http://127.0.0.1:8301";

    return [
      {
        source: "/v1/:path*",
        destination: `${api}/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${api}/health`,
      },
    ];
  },
};

export default nextConfig;
