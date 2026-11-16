import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Container } from "@/components/ui/section";
import { getPublishedArticle } from "@/lib/cms/cms";

type PageProps = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const article = await getPublishedArticle(slug);
  if (!article) return { title: "Update not found" };
  return {
    title: article.seoTitle || article.title,
    description: article.seoDescription || article.excerpt,
  };
}

function articleText(contentJson: string): string {
  try {
    const parsed = JSON.parse(contentJson) as { text?: string };
    return parsed.text ?? "";
  } catch {
    return "";
  }
}

export default async function NewsArticlePage({ params }: PageProps) {
  const { slug } = await params;
  const article = await getPublishedArticle(slug);
  if (!article) notFound();
  const text = articleText(article.contentJson);

  return (
    <section className="py-16 sm:py-20">
      <Container className="max-w-3xl">
        <Badge variant="outline">{article.category}</Badge>
        <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
          {article.title}
        </h1>
        {article.publishedAt ? (
          <p className="mt-4 text-sm font-medium text-slate-500">
            {format(article.publishedAt, "MMMM d, yyyy")}
          </p>
        ) : null}
        <div className="mt-8 grid gap-5 text-base leading-8 text-slate-700">
          {text.split(/\n{2,}/).map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>
      </Container>
    </section>
  );
}
