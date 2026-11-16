import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/admin",
          "/members",
          "/login",
          "/activate",
          "/forgot-password",
          "/api/",
        ],
      },
    ],
    sitemap: "https://defend-network.org/sitemap.xml",
  };
}
