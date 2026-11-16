import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { listPublishedArticles } from "@/lib/cms/cms";

export const metadata: Metadata = {
  title: "News & Updates",
  description: "DEFEND organizational news and updates.",
};

export const dynamic = "force-dynamic";

export default async function NewsPage() {
  const articles = await listPublishedArticles();

  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>News &amp; updates</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Organizational updates.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              Published updates from DEFEND. Only real, approved content appears
              here.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container>
          {articles.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center">
                <h2 className="text-lg font-semibold">No published updates yet</h2>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
                  Organizational updates will be published here when they are
                  ready.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {articles.map((article) => (
                <Card key={article.id} className="flex h-full flex-col">
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{article.category}</Badge>
                      {article.publishedAt ? (
                        <span className="text-xs text-slate-500">{format(article.publishedAt, "MMM d, yyyy")}</span>
                      ) : null}
                    </div>
                    <CardTitle>{article.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col">
                    <p className="text-sm leading-6 text-slate-600">{article.excerpt}</p>
                    <div className="mt-auto pt-5">
                      <Button asChild variant="secondary" size="sm">
                        <Link href={`/news/${article.slug}`}>Read update</Link>
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </Container>
      </section>
    </>
  );
}
