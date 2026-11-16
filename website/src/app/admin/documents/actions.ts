"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import { uploadDocument } from "@/lib/documents/documents";
import type { DocumentActionState } from "./action-state";

export async function uploadDocumentAction(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  try {
    const actor = await getActor();
    if (!actor || !can(actor, "documents.manage")) {
      throw new Error("MFA-verified document-management access is required.");
    }
    const file = formData.get("file");
    if (!(file instanceof File)) {
      return { status: "error", message: "Select a file." };
    }
    const context = await requestAuditContext();
    const result = await uploadDocument({
      actor,
      file,
      title: String(formData.get("title") ?? ""),
      description: String(formData.get("description") ?? ""),
      category: String(formData.get("category") ?? "general"),
      visibility: String(formData.get("visibility") ?? "admin"),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/documents");
    return { status: "success", message: "Document uploaded." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Upload failed.",
    };
  }
}
