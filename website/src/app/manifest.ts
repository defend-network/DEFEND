import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DEFEND",
    short_name: "DEFEND",
    description:
      "DEFEND is a fraternal, cultural, and economic network being organized in Pasco County, Florida.",
    start_url: "/",
    display: "standalone",
    background_color: "#f7f8fa",
    theme_color: "#101f38",
    icons: [
      {
        src: "/defend-logo.png",
        sizes: "1024x1024",
        type: "image/png",
      },
    ],
  };
}
