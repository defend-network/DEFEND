import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Container, Eyebrow } from "@/components/ui/section";
import { getProgram, programs } from "@/lib/content/programs";

type PageProps = { params: Promise<{ slug: string }> };

export function generateStaticParams() {
  return programs.map((program) => ({ slug: program.slug }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const program = getProgram(slug);
  if (!program) return { title: "Program not found" };
  return {
    title: program.title,
    description: program.summary,
  };
}

export default async function ProgramPage({ params }: PageProps) {
  const { slug } = await params;
  const program = getProgram(slug);
  if (!program) notFound();

  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <Eyebrow>Program</Eyebrow>
              <StatusBadge status={program.status} />
            </div>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              {program.title}
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              {program.summary}
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container className="grid gap-12 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <p className="text-pretty text-base leading-8 text-slate-700">
              {program.description}
            </p>
            <div className="mt-8 flex flex-wrap gap-2">
              {program.focus.map((focus) => (
                <Badge key={focus} variant="outline">
                  {focus}
                </Badge>
              ))}
            </div>
            <Alert tone="info" className="mt-8">
              This program is labeled <strong>{program.status.replaceAll("_", " ")}</strong>.
              DEFEND will publish a schedule, location, and participant process
              only when they are confirmed.
            </Alert>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild>
                <Link href="/apply">Apply for membership</Link>
              </Button>
              <Button asChild variant="secondary">
                <Link href="/programs">All programs</Link>
              </Button>
            </div>
          </div>
          <aside className="rounded-[var(--radius-panel)] border border-slate-200 bg-white p-6">
            <h2 className="text-lg font-semibold">Program status</h2>
            <dl className="mt-5 grid gap-4 text-sm">
              <div>
                <dt className="font-semibold text-navy-900">Current label</dt>
                <dd className="mt-1 text-slate-600">
                  {program.status.replaceAll("_", " ")}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-navy-900">Chapter</dt>
                <dd className="mt-1 text-slate-600">
                  Pasco County founding chapter (in development)
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-navy-900">Participation</dt>
                <dd className="mt-1 text-slate-600">
                  Not yet open unless explicitly stated.
                </dd>
              </div>
            </dl>
          </aside>
        </Container>
      </section>
    </>
  );
}
