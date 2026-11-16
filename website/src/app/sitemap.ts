import type { MetadataRoute } from "next";

import { siteConfig } from "@/lib/config/site";
import { programs } from "@/lib/content/programs";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const publicPaths = [
    "",
    "/about",
    "/programs",
    "/chapters",
    "/events",
    "/membership",
    "/apply",
    "/contact",
  ];

  return [
    ...publicPaths.map((path) => ({
      url: `${siteConfig.url}${path}`,
      lastModified: now,
      changeFrequency: path === "" ? ("weekly" as const) : ("monthly" as const),
      priority: path === "" ? 1 : path === "/apply" ? 0.9 : 0.7,
    })),
    ...programs.map((program) => ({
      url: `${siteConfig.url}/programs/${program.slug}`,
      lastModified: now,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
