import {
  ArrowRight,
  BookOpen,
  Building2,
  Dumbbell,
  Handshake,
  HeartHandshake,
  Landmark,
  ShieldCheck,
  Users,
} from "lucide-react";
import Link from "next/link";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Container, Eyebrow, SectionHeading } from "@/components/ui/section";
import { siteConfig } from "@/lib/config/site";
import { chapters, plannedChapters } from "@/lib/content/chapters";
import { programs } from "@/lib/content/programs";

const pillars = [
  {
    title: "Heritage",
    description:
      "Honoring European heritage and the traditions that shaped American community life, while passing them on to the next generation.",
    icon: Landmark,
  },
  {
    title: "Fellowship",
    description:
      "Building durable friendships and mutual obligations through local chapters, shared activities, and service.",
    icon: Users,
  },
  {
    title: "Economic Opportunity",
    description:
      "Supporting entrepreneurship, trades, mentorship, and a trusted member network that helps people build useful careers and businesses.",
    icon: Building2,
  },
  {
    title: "Service",
    description:
      "Encouraging personal responsibility, volunteer service, and practical contributions to the communities where members live.",
    icon: HeartHandshake,
  },
];

const membershipSteps = [
  {
    title: "Apply",
    description:
      "Submit an application with your background, interests, and the chapter you want to join.",
  },
  {
    title: "Review",
    description:
      "An administrator reviews the application. DEFEND does not automate membership decisions.",
  },
  {
    title: "Activate",
    description:
      "Approved applicants receive an invitation to create an account and access the member portal.",
  },
  {
    title: "Dues",
    description:
      "Paid membership follows the approved tier catalog. Online billing will be enabled only after legal and financial readiness is confirmed.",
  },
];

export default function HomePage() {
  return (
    <>
      <section className="relative overflow-hidden bg-navy-900 text-white">
        <div className="institutional-grid absolute inset-0 opacity-40" />
        <div className="absolute inset-x-0 top-0 h-1 bg-red-600" />
        <Container className="relative py-20 sm:py-28 lg:py-32">
          <div className="grid items-center gap-14 lg:grid-cols-[1.25fr_0.75fr]">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="red" className="bg-red-600 text-white">
                  Pasco County, Florida
                </Badge>
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-300">
                  Founding chapter in development
                </span>
              </div>
              <h1 className="mt-7 text-balance text-4xl font-semibold leading-[1.05] text-white sm:text-6xl">
                A fraternal network built for the next generation.
              </h1>
              <p className="mt-6 max-w-2xl text-pretty text-lg leading-8 text-slate-200">
                DEFEND brings together Americans interested in European heritage
                for cultural preservation, fraternal fellowship, economic
                development, trades education, mentorship, fitness, and
                community service.
              </p>
              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                <Button asChild size="lg">
                  <Link href="/apply">
                    Apply for Membership
                    <ArrowRight size={18} aria-hidden="true" />
                  </Link>
                </Button>
                <Button
                  asChild
                  size="lg"
                  variant="secondary"
                  className="border-white/25 bg-white/10 text-white hover:border-white/40 hover:bg-white/15"
                >
                  <Link href="/about">Explore Our Mission</Link>
                </Button>
              </div>
            </div>

            <aside className="rounded-[var(--radius-panel)] border border-white/15 bg-white/[0.06] p-6 backdrop-blur-sm">
              <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#f0a0aa]">
                Current status
              </p>
              <dl className="mt-5 grid gap-5">
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                    Organization
                  </dt>
                  <dd className="mt-1 text-sm leading-6 text-slate-200">
                    Not yet incorporated. No IRS recognition of tax-exempt
                    status has been received.
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                    First chapter
                  </dt>
                  <dd className="mt-1 text-sm leading-6 text-slate-200">
                    Pasco County is in development. Founding participants are
                    being recruited.
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                    Membership
                  </dt>
                  <dd className="mt-1 text-sm leading-6 text-slate-200">
                    Applications are open. Membership tiers and current pricing
                    are listed on the membership page. Online billing is not
                    active.
                  </dd>
                </div>
              </dl>
            </aside>
          </div>
        </Container>
      </section>

      <section className="border-b border-slate-200 bg-white">
        <Container className="grid gap-6 py-6 sm:grid-cols-3">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 size-5 text-red-700" aria-hidden="true" />
            <p className="text-sm leading-6">
              <strong className="text-navy-900">Organized lawfully.</strong>{" "}
              Membership applications are reviewed manually under written
              criteria.
            </p>
          </div>
          <div className="flex items-start gap-3">
            <Users className="mt-0.5 size-5 text-red-700" aria-hidden="true" />
            <p className="text-sm leading-6">
              <strong className="text-navy-900">Local first.</strong> The
              founding chapter is being organized in Pasco County, Florida.
            </p>
          </div>
          <div className="flex items-start gap-3">
            <Handshake className="mt-0.5 size-5 text-red-700" aria-hidden="true" />
            <p className="text-sm leading-6">
              <strong className="text-navy-900">One standard tier.</strong>{" "}
              DEFEND does not currently offer premium membership tiers.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-20 sm:py-24">
        <Container>
          <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
            <SectionHeading
              eyebrow="What DEFEND is"
              title="A serious organization, built in the open."
              description="DEFEND is an early-stage fraternal, cultural, and economic organization. It is not yet incorporated, has no established facilities, and is not presenting planned programs as completed achievements."
            />
            <div className="grid gap-5 sm:grid-cols-2">
              {pillars.map((pillar) => {
                const Icon = pillar.icon;
                return (
                  <Card key={pillar.title} className="h-full">
                    <CardHeader>
                      <Icon className="size-6 text-red-700" aria-hidden="true" />
                      <CardTitle>{pillar.title}</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm leading-6 text-slate-600">
                        {pillar.description}
                      </p>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        </Container>
      </section>

      <section className="border-y border-slate-200 bg-white py-20 sm:py-24">
        <Container>
          <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
            <SectionHeading
              eyebrow="Programs"
              title="What membership is being built to support."
              description="These are the areas DEFEND is developing. Status labels distinguish what is operating from what is still planned."
            />
            <Button asChild variant="secondary">
              <Link href="/programs">View all programs</Link>
            </Button>
          </div>

          <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {programs.map((program) => (
              <Card key={program.slug} className="flex h-full flex-col">
                <CardHeader>
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant="outline">{program.focus[0]}</Badge>
                    <StatusBadge status={program.status} />
                  </div>
                  <CardTitle>{program.title}</CardTitle>
                  <CardDescription>{program.summary}</CardDescription>
                </CardHeader>
                <CardContent className="mt-auto">
                  <Link
                    href={`/programs/${program.slug}`}
                    className="inline-flex items-center gap-2 text-sm font-semibold text-red-700 underline-offset-4 hover:underline"
                  >
                    Read more <ArrowRight size={15} aria-hidden="true" />
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>
        </Container>
      </section>

      <section className="py-20 sm:py-24">
        <Container>
          <div className="grid gap-12 lg:grid-cols-[1fr_1fr] lg:items-center">
            <div>
              <SectionHeading
                eyebrow="Chapters"
                title="The first chapter is being organized in Pasco County."
                description="DEFEND is building its founding chapter deliberately. Additional Florida chapters are planned, but they are not operating and have no assigned members."
              />
              <div className="mt-8 grid gap-4">
                {chapters.map((chapter) => (
                  <Card key={chapter.slug}>
                    <CardContent className="flex items-start justify-between gap-5 p-6">
                      <div>
                        <div className="flex flex-wrap items-center gap-3">
                          <h3 className="text-lg font-semibold">{chapter.name}</h3>
                          <StatusBadge status={chapter.status} />
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          {chapter.description}
                        </p>
                      </div>
                      <Landmark className="size-6 shrink-0 text-red-700" aria-hidden="true" />
                    </CardContent>
                  </Card>
                ))}
              </div>
              <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-slate-500">
                <span className="font-semibold text-navy-900">Planned:</span>
                {plannedChapters.map((chapter) => (
                  <span key={chapter.slug} className="inline-flex items-center gap-2">
                    {chapter.name}
                    <StatusBadge status={chapter.status} />
                  </span>
                ))}
              </div>
            </div>

            <Card className="border-navy-800/10 bg-navy-900 text-white">
              <CardHeader>
                <Eyebrow className="text-[#f0a0aa]">Founding participation</Eyebrow>
                <CardTitle className="text-white">
                  Help shape the first chapter.
                </CardTitle>
                <CardDescription className="text-slate-300">
                  DEFEND is recruiting founding participants for Pasco County.
                  The founding cohort is a plan, not an existing membership
                  count.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <ul className="grid gap-3 text-sm leading-6 text-slate-200">
                  <li className="flex gap-3">
                    <Users className="mt-0.5 size-4 shrink-0 text-red-500" aria-hidden="true" />
                    Participate in the formation of a local chapter.
                  </li>
                  <li className="flex gap-3">
                    <Handshake className="mt-0.5 size-4 shrink-0 text-red-500" aria-hidden="true" />
                    Help define practical programs and service priorities.
                  </li>
                  <li className="flex gap-3">
                    <Dumbbell className="mt-0.5 size-4 shrink-0 text-red-500" aria-hidden="true" />
                    Contribute skills, trades experience, and community knowledge.
                  </li>
                </ul>
                <Button asChild>
                  <Link href="/apply">Start an application</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </Container>
      </section>

      <section className="border-y border-slate-200 bg-white py-20 sm:py-24">
        <Container>
          <div className="grid gap-12 lg:grid-cols-[0.8fr_1.2fr]">
            <SectionHeading
              eyebrow="Membership"
              title="Membership tiers for participation and support."
              description="Four tiers are defined: Free, Standard, Supporter, and Patron. Current prices and benefits are published from the approved catalog."
            />
            <div className="grid gap-4 sm:grid-cols-2">
              {membershipSteps.map((step, index) => (
                <Card key={step.title}>
                  <CardHeader>
                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-red-700">
                      Step {index + 1}
                    </span>
                    <CardTitle>{step.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm leading-6 text-slate-600">
                      {step.description}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
          <div className="mt-10 flex flex-col gap-4 rounded-[var(--radius-panel)] border border-slate-200 bg-paper p-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <BookOpen className="mt-0.5 size-5 text-red-700" aria-hidden="true" />
              <p className="max-w-2xl text-sm leading-6 text-slate-600">
                {siteConfig.status.legal} {siteConfig.status.billing}
              </p>
            </div>
            <Button asChild variant="secondary">
              <Link href="/membership">Membership details</Link>
            </Button>
          </div>
        </Container>
      </section>

      <section className="bg-navy-900 py-20 text-white sm:py-24">
        <Container className="text-center">
          <Eyebrow className="text-[#f0a0aa]">Apply for membership</Eyebrow>
          <h2 className="mx-auto mt-4 max-w-3xl text-balance text-3xl font-semibold leading-tight text-white sm:text-4xl">
            If this mission fits you, we invite you to apply.
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-pretty text-base leading-7 text-slate-300">
            Every application is reviewed by a person. Approved applicants will
            be able to activate an account before live billing is enabled.
          </p>
          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <Button asChild size="lg">
              <Link href="/apply">Apply for Membership</Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="secondary"
              className="border-white/25 bg-white/10 text-white hover:border-white/40 hover:bg-white/15"
            >
              <Link href="/contact">Contact DEFEND</Link>
            </Button>
          </div>
        </Container>
      </section>
    </>
  );
}
