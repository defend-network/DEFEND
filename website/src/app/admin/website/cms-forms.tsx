"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createAnnouncementAction,
  createArticleAction,
  createPageAction,
  publishCmsAction,
} from "./actions";
import { initialCmsActionState, type CmsActionState } from "./action-state";

function Result({ state }: { state: CmsActionState }) {
  if (state.status === "idle") return null;
  return <div className="mt-3"><Alert tone={state.status === "success" ? "success" : "error"}>{state.message}</Alert></div>;
}

export function PageForm() {
  const [state, action, pending] = useActionState(createPageAction, initialCmsActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New CMS page</h2>
      <div className="grid gap-2"><Label htmlFor="page-title">Title</Label><Input id="page-title" name="title" required /></div>
      <div className="grid gap-2"><Label htmlFor="page-slug">Slug (optional)</Label><Input id="page-slug" name="slug" placeholder="about-our-chapter" /></div>
      <div className="grid gap-2"><Label htmlFor="page-text">Content</Label><Textarea id="page-text" name="text" required /></div>
      <div className="grid gap-2"><Label htmlFor="page-seo-title">SEO title</Label><Input id="page-seo-title" name="seoTitle" /></div>
      <div className="grid gap-2"><Label htmlFor="page-seo-description">SEO description</Label><Textarea id="page-seo-description" name="seoDescription" /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="publish" className="size-4 accent-red-600" />Publish immediately</label>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create page"}</Button>
      <Result state={state} />
    </form>
  );
}

export function ArticleForm() {
  const [state, action, pending] = useActionState(createArticleAction, initialCmsActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New article</h2>
      <div className="grid gap-2"><Label htmlFor="article-title">Title</Label><Input id="article-title" name="title" required /></div>
      <div className="grid gap-2"><Label htmlFor="article-slug">Slug (optional)</Label><Input id="article-slug" name="slug" /></div>
      <div className="grid gap-2"><Label htmlFor="article-category">Category</Label>
        <select id="article-category" name="category" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="news">News</option><option value="chapter">Chapter</option><option value="programs">Programs</option><option value="heritage">Heritage</option>
        </select>
      </div>
      <div className="grid gap-2"><Label htmlFor="article-excerpt">Excerpt</Label><Textarea id="article-excerpt" name="excerpt" /></div>
      <div className="grid gap-2"><Label htmlFor="article-text">Content</Label><Textarea id="article-text" name="text" required /></div>
      <div className="grid gap-2"><Label htmlFor="article-seo-title">SEO title</Label><Input id="article-seo-title" name="seoTitle" /></div>
      <div className="grid gap-2"><Label htmlFor="article-seo-description">SEO description</Label><Textarea id="article-seo-description" name="seoDescription" /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="publish" className="size-4 accent-red-600" />Publish immediately</label>
      <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create article"}</Button>
      <Result state={state} />
    </form>
  );
}

export function AnnouncementForm() {
  const [state, action, pending] = useActionState(createAnnouncementAction, initialCmsActionState);
  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">New announcement</h2>
      <div className="grid gap-2"><Label htmlFor="announcement-title">Title</Label><Input id="announcement-title" name="title" required /></div>
      <div className="grid gap-2"><Label htmlFor="announcement-body">Body</Label><Textarea id="announcement-body" name="body" required /></div>
      <div className="grid gap-2"><Label htmlFor="announcement-visibility">Visibility</Label>
        <select id="announcement-visibility" name="visibility" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
          <option value="members">Members</option><option value="chapter">Chapter</option><option value="public">Public</option>
        </select>
      </div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Creating…" : "Create announcement"}</Button>
      <Result state={state} />
    </form>
  );
}

export function PublishToggle({
  entityType,
  entityId,
  published,
}: {
  entityType: "cms_page" | "cms_article";
  entityId: string;
  published: boolean;
}) {
  const [state, action, pending] = useActionState(publishCmsAction, initialCmsActionState);
  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="entityType" value={entityType} />
      <input type="hidden" name="entityId" value={entityId} />
      <input type="hidden" name="publish" value={published ? "false" : "true"} />
      <Button type="submit" variant={published ? "secondary" : "primary"} size="sm" disabled={pending}>
        {pending ? "Updating…" : published ? "Unpublish" : "Publish"}
      </Button>
      <Result state={state} />
    </form>
  );
}
