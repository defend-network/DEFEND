"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import { createChapter, updateChapterStatus } from "@/lib/chapters/admin";
import type { ChapterActionState } from "./action-state";

async function chapterActor() {
  const actor = await getActor();
  if (!actor || !can(actor, "chapters.manage")) {
    throw new Error("MFA-verified chapter-management access is required.");
  }
  return actor;
}

function value(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

export async function createChapterAction(
  _previous: ChapterActionState,
  formData: FormData,
): Promise<ChapterActionState> {
  try {
    const actor = await chapterActor();
    const name = value(formData, "name");
    const county = value(formData, "county");
    const state = value(formData, "state");
    if (!name || !county || !state) {
      return { status: "error", message: "Enter a name, county, and state." };
    }
    const context = await requestAuditContext();
    const result = await createChapter({
      actor,
      name,
      county,
      state,
      status: value(formData, "status") || "proposed",
      description: value(formData, "description"),
      contactEmail: value(formData, "contactEmail"),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/chapters");
    revalidatePath("/chapters");
    return { status: "success", message: "Chapter created." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Chapter creation failed." };
  }
}

export async function updateChapterStatusAction(
  _previous: ChapterActionState,
  formData: FormData,
): Promise<ChapterActionState> {
  try {
    const actor = await chapterActor();
    const context = await requestAuditContext();
    const result = await updateChapterStatus({
      actor,
      chapterId: value(formData, "chapterId"),
      status: value(formData, "status"),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/chapters");
    revalidatePath("/chapters");
    return { status: "success", message: "Chapter status updated." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Status update failed." };
  }
}
