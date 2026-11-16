import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Container, Eyebrow } from "@/components/ui/section";
import { listPublishedEvents } from "@/lib/events/events";

export const metadata: Metadata = {
  title: "Events",
  description: "Upcoming DEFEND events and gatherings.",
};

export const dynamic = "force-dynamic";

export default async function EventsPage() {
  const eventRows = await listPublishedEvents();

  return (
    <>
      <section className="border-b border-slate-200 bg-white py-16 sm:py-20">
        <Container>
          <div className="max-w-3xl">
            <Eyebrow>Events</Eyebrow>
            <h1 className="mt-5 text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              Gather with the chapter.
            </h1>
            <p className="mt-6 text-pretty text-lg leading-8 text-slate-600">
              Published DEFEND events appear here. Only confirmed events with a
              date and location are listed.
            </p>
          </div>
        </Container>
      </section>

      <section className="py-16 sm:py-20">
        <Container>
          {eventRows.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center">
                <h2 className="text-lg font-semibold">No published events yet</h2>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
                  The founding chapter is still organizing. Events will be
                  published when the date, location, and participant process are
                  confirmed.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {eventRows.map((event) => (
                <Card key={event.id} className="flex h-full flex-col">
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{event.chapterName ?? "Pasco County"}</Badge>
                      {event.capacity ? (
                        <Badge variant="amber">Capacity {event.capacity}</Badge>
                      ) : null}
                    </div>
                    <CardTitle>{event.title}</CardTitle>
                    <p className="text-sm font-medium text-slate-500">
                      {format(event.startsAt, "EEEE, MMMM d, yyyy · h:mm a")}
                    </p>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col">
                    <p className="text-sm leading-6 text-slate-600">{event.summary}</p>
                    <p className="mt-2 text-sm text-slate-500">
                      {event.locationName || "Location to be announced"}
                    </p>
                    <div className="mt-auto pt-5">
                      <Button asChild variant="secondary" size="sm">
                        <Link href={`/events/${event.slug}`}>Event details</Link>
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
