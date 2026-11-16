import type { Metadata } from "next";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listAnnouncements,
  listCmsArticles,
  listCmsPages,
} from "@/lib/cms/cms";
import {
  AnnouncementForm,
  ArticleForm,
  PageForm,
  PublishToggle,
} from "./cms-forms";

export const metadata: Metadata = {
  title: "Website CMS",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function WebsiteCmsPage() {
  const [pages, articles, announcements] = await Promise.all([
    listCmsPages(),
    listCmsArticles(),
    listAnnouncements(),
  ]);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Public content
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Website CMS</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Additional pages, news articles, and announcements with draft and
          published states, SEO metadata, and revision records.
        </p>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <PageForm />
        <ArticleForm />
        <AnnouncementForm />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>CMS pages</CardTitle></CardHeader>
          <CardContent>
            {pages.length === 0 ? <p className="text-sm text-slate-500">No CMS pages.</p> : (
              <ul className="grid gap-3">
                {pages.map((page) => (
                  <li key={page.id} className="grid gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="font-semibold text-navy-900">{page.title}</p>
                        <p className="text-xs text-slate-500">/pages/{page.slug} · {format(page.updatedAt, "MMM d, yyyy")}</p>
                      </div>
                      <Badge variant={page.status === "published" ? "green" : "outline"}>{page.status}</Badge>
                    </div>
                    <PublishToggle entityType="cms_page" entityId={page.id} published={page.status === "published"} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Articles</CardTitle></CardHeader>
          <CardContent>
            {articles.length === 0 ? <p className="text-sm text-slate-500">No articles.</p> : (
              <ul className="grid gap-3">
                {articles.map((article) => (
                  <li key={article.id} className="grid gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="font-semibold text-navy-900">{article.title}</p>
                        <p className="text-xs text-slate-500">/news/{article.slug} · {article.category}</p>
                      </div>
                      <Badge variant={article.status === "published" ? "green" : "outline"}>{article.status}</Badge>
                    </div>
                    <PublishToggle entityType="cms_article" entityId={article.id} published={article.status === "published"} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Announcements</CardTitle></CardHeader>
        <CardContent>
          {announcements.length === 0 ? <p className="text-sm text-slate-500">No announcements.</p> : (
            <ul className="grid gap-3">
              {announcements.map((announcement) => (
                <li key={announcement.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                  <p className="font-semibold text-navy-900">{announcement.title}</p>
                  <p className="mt-1 text-sm text-slate-600">{announcement.body}</p>
                  <p className="mt-1 text-xs text-slate-500">{announcement.visibility} · {announcement.publishedAt ? format(announcement.publishedAt, "MMM d, yyyy") : "draft"}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
