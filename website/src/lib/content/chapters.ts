import type { ContentStatus } from "@/lib/config/site";

export type ChapterSummary = {
  slug: string;
  name: string;
  area: string;
  status: ContentStatus;
  description: string;
};

export const chapters: ChapterSummary[] = [
  {
    slug: "pasco-county",
    name: "Pasco County",
    area: "Pasco County, Florida",
    status: "in_development",
    description:
      "The founding DEFEND chapter is being organized in Pasco County. Founding participants are being recruited, and chapter leadership and meeting details are still being confirmed.",
  },
];

export const plannedChapters: ChapterSummary[] = [
  {
    slug: "orlando",
    name: "Orlando",
    area: "Orange County, Florida",
    status: "planned",
    description:
      "A future chapter is planned for the Orlando area. It is not operating and has no assigned members.",
  },
  {
    slug: "pensacola",
    name: "Pensacola",
    area: "Escambia County, Florida",
    status: "planned",
    description:
      "A future chapter is planned for the Pensacola area. It is not operating and has no assigned members.",
  },
  {
    slug: "tallahassee",
    name: "Tallahassee",
    area: "Leon County, Florida",
    status: "planned",
    description:
      "A future chapter is planned for the Tallahassee area. It is not operating and has no assigned members.",
  },
];

export function getChapter(slug: string): ChapterSummary | undefined {
  return [...chapters, ...plannedChapters].find(
    (chapter) => chapter.slug === slug,
  );
}
