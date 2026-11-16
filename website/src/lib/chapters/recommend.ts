import type { ChapterSummary } from "@/lib/content/chapters";

export type ChapterRecommendation = {
  chapterId: string | null;
  reason: string;
  outOfArea: boolean;
};

const PASCO_ZIP_PREFIXES = ["34652", "34653", "34654", "34655", "34667", "34669", "34690"];

export function recommendChapter(input: {
  state: string;
  postalCode?: string | null;
  operatingChapters: ChapterSummary[];
}): ChapterRecommendation {
  const pasco = input.operatingChapters.find(
    (chapter) => chapter.slug === "pasco-county",
  );
  if (!pasco) {
    return {
      chapterId: null,
      reason: "No operating chapter is currently available.",
      outOfArea: true,
    };
  }

  const state = input.state.trim().toUpperCase();
  const zip = input.postalCode?.trim() ?? "";
  const inPascoZip = PASCO_ZIP_PREFIXES.some((prefix) => zip.startsWith(prefix));

  if (state === "FL") {
    return {
      chapterId: "chapter_pasco",
      reason: inPascoZip
        ? "Pasco County is the recommended founding chapter for your location."
        : "Pasco County is the only operating chapter in Florida. You may choose it as your founding chapter.",
      outOfArea: false,
    };
  }

  return {
    chapterId: "chapter_pasco",
    reason:
      "Pasco County is the only operating DEFEND chapter. Applicants outside Florida may still choose it, but local participation will require travel or future chapter development.",
    outOfArea: true,
  };
}
