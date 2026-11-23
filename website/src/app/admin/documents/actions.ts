"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { chapterIdsForPermission } from "@/lib/policy/permissions";
import {
  addDocumentVersion,
  archiveDocument,
  restoreDocumentVersion,
  uploadDocument,
} from "@/lib/documents/documents";
import type { DocumentActionState } from "./action-state";

export async function uploadDocumentAction(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");
    const scope = chapterIdsForPermission(actor, "documents.manage");
    if (scope !== "all" && scope.length === 0) {
      throw new Error("Document-management access is required.");
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

export async function addVersionAction(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");
    const file = formData.get("file");
    if (!(file instanceof File)) return { status: "error", message: "Select a file." };
    const context = await requestAuditContext();
    const result = await addDocumentVersion({
      actor,
      documentId: String(formData.get("documentId") ?? ""),
      file,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath(`/admin/documents/${formData.get("documentId")}`);
    return { status: "success", message: `Version ${result.version} uploaded.` };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Version upload failed." };
  }
}

export async function restoreVersionAction(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");
    const context = await requestAuditContext();
    const result = await restoreDocumentVersion({
      actor,
      documentId: String(formData.get("documentId") ?? ""),
      version: Number(formData.get("version") ?? 0),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath(`/admin/documents/${formData.get("documentId")}`);
    return { status: "success", message: `Restored as version ${result.version}.` };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Version restore failed." };
  }
}

export async function archiveDocumentAction(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  try {
    const actor = await getActor();
    if (!actor) throw new Error("Sign in to continue.");
    const context = await requestAuditContext();
    const result = await archiveDocument({
      actor,
      documentId: String(formData.get("documentId") ?? ""),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/documents");
    return { status: "success", message: "Document archived." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Archive failed." };
  }
}
