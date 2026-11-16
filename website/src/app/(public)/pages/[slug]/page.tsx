import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Container } from "@/components/ui/section";
import { getPublishedPage } from "@/lib/cms/cms";

type PageProps = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const result = await getPublishedPage(slug);
  if (!result) return { title: "Page not found" };
  return {
    title: result.page.seoTitle || result.page.title,
    description: result.page.seoDescription || undefined,
  };
}

function blockText(contentJson: string): string {
  try {
    const parsed = JSON.parse(contentJson) as { text?: string };
    return parsed.text ?? "";
  } catch {
    return "";
  }
}

export default async function CmsPage({ params }: PageProps) {
  const { slug } = await params;
  const result = await getPublishedPage(slug);
  if (!result) notFound();

  return (
    <section className="py-16 sm:py-20">
      <Container className="max-w-3xl">
        <h1 className="text-balance text-4xl font-semibold leading-tight sm:text-5xl">
          {result.page.title}
        </h1>
        <div className="mt-8 grid gap-5 text-base leading-8 text-slate-700">
          {result.blocks.map((block) => {
            const text = blockText(block.contentJson);
            if (!text) return null;
            return text.split(/\n{2,}/).map((paragraph, index) => (
              <p key={`${block.id}-${index}`}>{paragraph}</p>
            ));
          })}
        </div>
      </Container>
    </section>
  );
}
