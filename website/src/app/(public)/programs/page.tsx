import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { listPublicPrograms } from "@/lib/programs/programs";

export const metadata: Metadata = {
  title: "Programs",
  description:
    "Programs DEFEND is developing: trades and entrepreneurship, mentorship, fitness and boxing, cultural education, and community service.",
};

export const dynamic = "force-dynamic";

function statusVariant(status: string) {
  if (status === "operating") return "green" as const;
  if (status === "in_development") return "amber" as const;
  return "outline" as const;
}

export default async function ProgramsPage() {
  const programs = await listPublicPrograms();

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
          {programs.length === 0 ? (
            <Card><CardContent className="p-8 text-center"><h2 className="text-lg font-semibold">No published programs</h2><p className="mt-2 text-sm text-slate-500">Programs will appear here when they are configured and published.</p></CardContent></Card>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {programs.map((program) => (
                <Card key={program.id} className="flex h-full flex-col">
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={statusVariant(program.status)}>{program.status.replaceAll("_", " ")}</Badge>
                      {program.familyFriendly ? <Badge variant="outline">Family-friendly</Badge> : null}
                      {program.feeCents ? <Badge variant="outline">${(program.feeCents / 100).toFixed(2)} fee</Badge> : null}
                    </div>
                    <CardTitle>{program.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col">
                    <p className="text-sm leading-6 text-slate-600">{program.summary}</p>
                    <p className="mt-2 text-xs leading-5 text-slate-500">{program.eligibility || "Eligibility will be published with the program."}</p>
                    <div className="mt-auto pt-5">
                      <Button asChild variant="secondary" size="sm">
                        <Link href={`/programs/${program.slug}`}>Program details</Link>
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          <div className="mt-14 grid gap-8 border-t border-slate-200 pt-12 lg:grid-cols-[1fr_1fr]">
            <SectionHeading
              eyebrow="Status labels"
              title="What the labels mean."
              description="Operating means available now. In development means actively being built. Proposed means under consideration. Planned means intended for a future phase."
            />
            <div className="rounded-[var(--radius-panel)] border border-slate-200 bg-white p-6">
              <p className="text-sm leading-6 text-slate-600">
                No program is described as operating until there is a confirmed
                schedule, responsible leadership, and a real participant
                workflow. Standard membership does not automatically include free
                facility or program access.
              </p>
              <div className="mt-5">
                <Button asChild><Link href="/apply">Apply for membership</Link></Button>
              </div>
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
