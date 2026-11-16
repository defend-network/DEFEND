import type { Metadata } from "next";
import Link from "next/link";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { programs } from "@/lib/content/programs";

export const metadata: Metadata = {
  title: "Programs",
  description:
    "Programs DEFEND is developing: trades and entrepreneurship, mentorship, fitness and boxing, cultural education, and community service.",
};

export default function ProgramsPage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Programs</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              What membership is being built to support.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              These are the areas DEFEND is developing. Each program is labeled
              with its current status so planned work is not mistaken for an
              operating service.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container>
          <div className="grid gap-5 md:grid-cols-2">
            {programs.map((program) => (
              <Card key={program.slug} className="flex h-full flex-col">
                <CardHeader>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{program.focus[0]}</Badge>
                    <StatusBadge status={program.status} />
                  </div>
                  <CardTitle>{program.title}</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col">
                  <p className="text-sm leading-6 text-slate-600">
                    {program.summary}
                  </p>
                  <div className="mt-6 flex flex-wrap gap-2">
                    {program.focus.map((focus) => (
                      <span
                        key={focus}
                        className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600"
                      >
                        {focus}
                      </span>
                    ))}
                  </div>
                  <div className="mt-auto pt-6">
                    <Button asChild variant="secondary" size="sm">
                      <Link href={`/programs/${program.slug}`}>
                        Program details
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="mt-14 grid gap-8 border-t border-slate-200 pt-12 lg:grid-cols-[1fr_1fr]">
            <SectionHeading
              eyebrow="Status labels"
              title="What the labels mean."
              description="Operating means available now. In development means actively being built. Proposed means under consideration. Planned means intended for a future phase."
            />
            <div className="rounded-[var(--radius-panel)] border border-slate-200 bg-white p-6">
              <p className="text-sm leading-6 text-slate-600">
                No program should be described as operating until there is a
                confirmed schedule, responsible leadership, and a real
                participant workflow. DEFEND will publish those details when
                they exist.
              </p>
              <div className="mt-5">
                <Button asChild>
                  <Link href="/apply">Apply for membership</Link>
                </Button>
              </div>
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
