export const siteConfig = {
  name: "DEFEND",
  expandedName:
    "Descendants of Europeans Fraternal Economic Network for Development",
  domain: "defend-network.org",
  url: "https://defend-network.org",
  contactEmail: "chairman@defend-network.org",
  description:
    "DEFEND is a fraternal, cultural, and economic network being organized in Pasco County, Florida.",
  status: {
    legal:
      "DEFEND is not yet incorporated and has not received IRS recognition of tax-exempt status.",
    chapter:
      "The Pasco County founding chapter is in development. Membership applications are open.",
    billing:
      "Online dues and donations are not active. Approved members may access the member portal before live billing is enabled.",
  },
} as const;

export const publicNavigation = [
  { href: "/about", label: "About" },
  { href: "/programs", label: "Programs" },
  { href: "/chapters", label: "Chapters" },
  { href: "/events", label: "Events" },
  { href: "/membership", label: "Membership" },
  { href: "/contact", label: "Contact" },
] as const;

export const footerNavigation = [
  {
    heading: "Organization",
    links: [
      { href: "/about", label: "About DEFEND" },
      { href: "/programs", label: "Programs" },
      { href: "/chapters", label: "Chapters" },
      { href: "/membership", label: "Membership" },
    ],
  },
  {
    heading: "Members",
    links: [
      { href: "/login", label: "Member login" },
      { href: "/apply", label: "Apply for membership" },
      { href: "/contact", label: "Contact" },
    ],
  },
] as const;

export type ContentStatus = "operating" | "in_development" | "proposed" | "planned";

export const statusLabels: Record<ContentStatus, string> = {
  operating: "Operating",
  in_development: "In development",
  proposed: "Proposed",
  planned: "Planned",
};
