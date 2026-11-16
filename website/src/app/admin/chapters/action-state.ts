export type ChapterActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialChapterActionState: ChapterActionState = { status: "idle" };
