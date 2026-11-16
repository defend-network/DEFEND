import type { ContentStatus } from "@/lib/config/site";

export type Program = {
  slug: string;
  title: string;
  summary: string;
  description: string;
  status: ContentStatus;
  focus: string[];
};

export const programs: Program[] = [
  {
    slug: "trades-and-entrepreneurship",
    title: "Trades & Entrepreneurship",
    summary:
      "Practical support for members building skills, trades, and small businesses.",
    description:
      "DEFEND is developing a member network for trades education, professional development, referrals, and entrepreneurship. The network is intended to help members build useful relationships and share practical knowledge.",
    status: "in_development",
    focus: ["Skilled trades", "Small business", "Mentoring", "Referrals"],
  },
  {
    slug: "mentorship",
    title: "Mentorship",
    summary:
      "Connecting experienced members with people entering a trade or profession.",
    description:
      "A mentorship program is being designed to pair experienced members with participants who want guidance in a trade, profession, or business. Participation will be voluntary and subject to program rules.",
    status: "planned",
    focus: ["Career guidance", "Trade skills", "Professional development"],
  },
  {
    slug: "fitness-and-boxing",
    title: "Fitness & Boxing",
    summary:
      "Physical fitness, discipline, and athletic development through structured activity.",
    description:
      "DEFEND intends to support fitness and boxing activities as part of its commitment to personal responsibility and physical development. Any youth-focused activity will require approved safeguarding, consent, and supervision policies before it is enabled.",
    status: "planned",
    focus: ["Fitness", "Boxing", "Discipline", "Youth safeguarding review"],
  },
  {
    slug: "cultural-education",
    title: "Cultural Education",
    summary:
      "Heritage, history, and cultural learning for members and their families.",
    description:
      "DEFEND is developing educational and cultural activities that explore European heritage and its place in American community life. Public resources will be clearly separated from member-only materials.",
    status: "in_development",
    focus: ["Heritage", "History", "Cultural resources", "Family activities"],
  },
  {
    slug: "community-service",
    title: "Community Service",
    summary:
      "Volunteer service and local projects that strengthen the community.",
    description:
      "DEFEND is developing volunteer and community-service opportunities in Pasco County. Service projects will be announced only when they are confirmed and ready for participants.",
    status: "planned",
    focus: ["Volunteer service", "Local projects", "Mutual aid"],
  },
];

export function getProgram(slug: string): Program | undefined {
  return programs.find((program) => program.slug === slug);
}
