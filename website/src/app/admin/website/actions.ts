"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import {
  createAnnouncement,
  createCmsArticle,
  createCmsPage,
  publishCmsEntity,
} from "@/lib/cms/cms";
import { cmsWritePermission } from "@/lib/cms/permissions";
import type { CmsActionState } from "./action-state";

async function cmsActor(permission: "cms.edit" | "cms.publish" = "cms.edit") {
  const actor = await getActor();
  if (!actor || !can(actor, permission)) {
    throw new Error(
      permission === "cms.publish"
        ? "MFA-verified publishing access is required."
        : "CMS access is required.",
    );
  }
  return actor;
}

function value(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

export async function createPageAction(
  _previous: CmsActionState,
  formData: FormData,
): Promise<CmsActionState> {
  try {
    const publish = formData.get("publish") === "on";
    const actor = await cmsActor(cmsWritePermission({ publish }));
    const title = value(formData, "title");
    if (!title) return { status: "error", message: "Enter a title." };
    const context = await requestAuditContext();
    const result = await createCmsPage({
      actor,
      title,
      slug: value(formData, "slug"),
      text: value(formData, "text"),
      seoTitle: value(formData, "seoTitle"),
      seoDescription: value(formData, "seoDescription"),
      publish,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/website");
    return { status: "success", message: `Page created at /pages/${result.slug}.` };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Page creation failed." };
  }
}

export async function createArticleAction(
  _previous: CmsActionState,
  formData: FormData,
): Promise<CmsActionState> {
  try {
    const publish = formData.get("publish") === "on";
    const actor = await cmsActor(cmsWritePermission({ publish }));
    const title = value(formData, "title");
    if (!title) return { status: "error", message: "Enter a title." };
    const context = await requestAuditContext();
    const result = await createCmsArticle({
      actor,
      title,
      slug: value(formData, "slug"),
      excerpt: value(formData, "excerpt"),
      text: value(formData, "text"),
      category: value(formData, "category") || "news",
      seoTitle: value(formData, "seoTitle"),
      seoDescription: value(formData, "seoDescription"),
      publish,
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/website");
    revalidatePath("/news");
    return { status: "success", message: `Article created at /news/${result.slug}.` };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Article creation failed." };
  }
}

export async function createAnnouncementAction(
  _previous: CmsActionState,
  formData: FormData,
): Promise<CmsActionState> {
  try {
    const visibility = value(formData, "visibility") || "members";
    const actor = await cmsActor(cmsWritePermission({ visibility }));
    const title = value(formData, "title");
    const body = value(formData, "body");
    if (!title || !body) return { status: "error", message: "Enter a title and body." };
    const context = await requestAuditContext();
    await createAnnouncement({
      actor,
      title,
      body,
      visibility,
      ...context,
    });
    revalidatePath("/admin/website");
    return { status: "success", message: "Announcement created." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Announcement creation failed." };
  }
}

export async function publishCmsAction(
  _previous: CmsActionState,
  formData: FormData,
): Promise<CmsActionState> {
  try {
    const actor = await cmsActor("cms.publish");
    const context = await requestAuditContext();
    await publishCmsEntity({
      actor,
      entityType: formData.get("entityType") === "cms_article" ? "cms_article" : "cms_page",
      entityId: String(formData.get("entityId") ?? ""),
      publish: formData.get("publish") === "true",
      ...context,
    });
    revalidatePath("/admin/website");
    revalidatePath("/news");
    return { status: "success", message: "Publishing status updated." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Publishing failed." };
  }
}
