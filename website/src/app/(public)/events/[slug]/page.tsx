import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container } from "@/components/ui/section";
import { getActor } from "@/lib/auth/session";
import { getEventBySlug, getMemberEventState } from "@/lib/events/events";
import { EventRegistrationForm } from "./registration-form";

type PageProps = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const event = await getEventBySlug(slug);
  if (!event) return { title: "Event not found" };
  return { title: event.title, description: event.summary };
}

export default async function EventDetailPage({ params }: PageProps) {
  const { slug } = await params;
  const event = await getEventBySlug(slug);
  if (!event) notFound();
  const actor = await getActor();
  const memberState = actor ? await getMemberEventState(actor.userId) : null;
  const alreadyRegistered = Boolean(
    memberState?.registrations.some(
      (registration) =>
        registration.eventId === event.id &&
        registration.status !== "cancelled",
    ),
  );

  return (
    <section className="py-16 sm:py-20">
      <Container className="grid gap-10 lg:grid-cols-[1.2fr_0.8fr]">
        <div>
          <Badge variant="outline">{event.chapterName ?? "Pasco County"}</Badge>
          <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
            {event.title}
          </h1>
          <p className="mt-4 text-lg font-medium text-slate-500">
            {format(event.startsAt, "EEEE, MMMM d, yyyy · h:mm a")}
          </p>
          <p className="mt-6 text-pretty text-base leading-8 text-slate-700">
            {event.description || event.summary}
          </p>
          <div className="mt-6 grid gap-2 text-sm text-slate-600">
            <p><strong className="text-navy-900">Location:</strong> {event.locationName || "To be announced"}</p>
            {event.address ? <p><strong className="text-navy-900">Address:</strong> {event.address}</p> : null}
            {event.capacity ? <p><strong className="text-navy-900">Capacity:</strong> {event.capacity}</p> : null}
          </div>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Registration</CardTitle>
          </CardHeader>
          <CardContent>
            <EventRegistrationForm
              eventId={event.id}
              signedIn={Boolean(actor)}
              alreadyRegistered={alreadyRegistered}
            />
            <p className="mt-4 text-xs leading-5 text-slate-500">
              Registration is limited to eligible members. The system records
              registered, waitlisted, and attended states without claiming
              attendance before check-in.
            </p>
          </CardContent>
        </Card>
      </Container>
    </section>
  );
}
