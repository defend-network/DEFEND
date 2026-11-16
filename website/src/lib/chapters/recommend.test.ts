import { describe, expect, it } from "vitest";

import { recommendChapter } from "@/lib/chapters/recommend";
import { chapters } from "@/lib/content/chapters";

describe("chapter recommendation", () => {
  it("recommends the Pasco founding chapter for Florida applicants", () => {
    const result = recommendChapter({
      state: "FL",
      postalCode: "34652",
      operatingChapters: chapters,
    });
    expect(result.chapterId).toBe("chapter_pasco");
    expect(result.outOfArea).toBe(false);
    expect(result.reason).toMatch(/Pasco County/i);
  });

  it("still recommends Pasco outside Florida with an out-of-area warning", () => {
    const result = recommendChapter({
      state: "GA",
      postalCode: "30060",
      operatingChapters: chapters,
    });
    expect(result.chapterId).toBe("chapter_pasco");
    expect(result.outOfArea).toBe(true);
    expect(result.reason).toMatch(/outside Florida/i);
  });

  it("returns no chapter when none is operating", () => {
    const result = recommendChapter({
      state: "FL",
      operatingChapters: [],
    });
    expect(result.chapterId).toBeNull();
    expect(result.outOfArea).toBe(true);
  });
});
