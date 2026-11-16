import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { chapters, plannedChapters } from "@/lib/content/chapters";

export const metadata: Metadata = {
  title: "Chapters",
  description:
    "The DEFEND founding chapter is in development in Pasco County, Florida. Additional Florida chapters are planned.",
};

export default function ChaptersPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Chapters</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Local chapters are the foundation.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              DEFEND is starting with one founding chapter in Pasco County,
              Florida. Additional chapters are planned, but they are not
              operating and have no assigned members.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container>
          <SectionHeading
            eyebrow="Founding chapter"
            title="Pasco County is in development."
            description="The chapter is being organized. Founding participants are being recruited, and leadership, meeting details, and program schedules are still being confirmed."
          />
          <div className="mt-8 grid gap-5 lg:grid-cols-2">
            {chapters.map((chapter) => (
              <Card key={chapter.slug}>
                <CardHeader>
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle>{chapter.name}</CardTitle>
                    <StatusBadge status={chapter.status} />
                  </div>
                  <p className="text-sm font-medium text-slate-500">
                    {chapter.area}
                  </p>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-6 text-slate-600">
                    {chapter.description}
                  </p>
                  <div className="mt-6">
                    <Button asChild variant="secondary" size="sm">
                      <Link href="/apply">Apply for the founding chapter</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Alert tone="warning" className="mt-8">
            Pasco County is not yet labeled operational. The chapter is in
            development and will be described as operating only when there is
            verified evidence of an active chapter.
          </Alert>

          <div className="mt-16 border-t border-slate-200 pt-12">
            <SectionHeading
              eyebrow="Planned expansion"
              title="Future Florida chapters."
              description="These locations are planned only. They are not operating chapters, have no assigned members, and should not be treated as available membership options."
            />
            <div className="mt-8 grid gap-4 md:grid-cols-3">
              {plannedChapters.map((chapter) => (
                <Card key={chapter.slug}>
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle>{chapter.name}</CardTitle>
                      <StatusBadge status={chapter.status} />
                    </div>
                    <p className="text-sm font-medium text-slate-500">
                      {chapter.area}
                    </p>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm leading-6 text-slate-600">
                      {chapter.description}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
